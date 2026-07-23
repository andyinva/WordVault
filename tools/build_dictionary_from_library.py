#!/usr/bin/env python3
"""
build_dictionary_from_library.py - grow the spelling dictionary from the
author's OWN writing, and report probable recurring typos.

The insight (learned from a 30-million-word corpus): a standard
dictionary flags tens of thousands of legitimate words in specialized
writing - KJV English (maketh, sware), Hebrew transliteration (erets,
melekh), theological vocabulary (substitutionary). But an author's own
frequency data separates vocabulary from mistakes:

  * a word used MANY times is vocabulary -> dictionary candidate;
  * UNLESS it sits one edit away from a word the author uses far more
    often - then it is a probable recurring typo (christain vs
    christian) -> reported for fixing, never whitelisted;
  * rare unknowns are left alone: the live spell checker flags them.

Usage:

    python tools/build_dictionary_from_library.py            # report only
    python tools/build_dictionary_from_library.py --apply    # also append
                                                  # to the user dictionary

Writes two review files next to the library:
    dictionary_candidates.txt   words to accept (applied with --apply)
    probable_typos.txt          recurring typos, with suggested fixes -
                                fix them with Library Search's staged
                                replace (Ctrl+Shift+F) in the editor
"""

from __future__ import annotations

import argparse
import getpass
import re
import string
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wordvault.storage.encryption import is_encrypted_database  # noqa: E402
from wordvault.storage.store import DocumentStore  # noqa: E402

WORD = re.compile(r"[A-Za-z][A-Za-z']+")

#: Vocabulary threshold: used at least this often = the author's word.
DEFAULT_THRESHOLD = 10
#: Typo test: correction used at least this many times more than the word.
TYPO_RATIO = 25


def default_library_path() -> Path:
    return Path.home() / ".wordvault" / "library.db"


def edits1(word: str) -> set[str]:
    """All strings one edit away (delete/transpose/replace/insert)."""
    splits = [(word[:i], word[i:]) for i in range(len(word) + 1)]
    out: set[str] = set()
    for a, b in splits:
        if b:
            out.add(a + b[1:])
        if len(b) > 1:
            out.add(a + b[1] + b[0] + b[2:])
        for c in string.ascii_lowercase:
            if b:
                out.add(a + c + b[1:])
            out.add(a + c + b)
    out.discard(word)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", default=None,
                        help="library database (default: ~/.wordvault/library.db)")
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD,
                        help=f"uses needed to count as vocabulary "
                             f"(default {DEFAULT_THRESHOLD})")
    parser.add_argument("--apply", action="store_true",
                        help="append the candidates to the user dictionary")
    args = parser.parse_args(argv)

    try:
        from spellchecker import SpellChecker
    except ImportError:
        print("This tool needs pyspellchecker:  pip install pyspellchecker")
        return 1

    library = Path(args.library) if args.library else default_library_path()
    passphrase = None
    if is_encrypted_database(library):
        passphrase = getpass.getpass("Library passphrase: ")

    # ---- count every word in every document's current text ----
    counts: Counter[str] = Counter()
    with DocumentStore(library, passphrase=passphrase) as store:
        docs = store.list_documents()
        print(f"Scanning {len(docs)} documents...")
        for i, doc in enumerate(docs, 1):
            for word in WORD.findall(store.current_text(doc.id)):
                counts[word.lower().strip("'")] += 1
            if i % 300 == 0:
                print(f"  {i}/{len(docs)}...")
    counts.pop("", None)
    print(f"{sum(counts.values()):,} words, {len(counts):,} distinct.")

    # ---- classify the unknowns ----
    spell = SpellChecker()
    unknown = spell.unknown(set(counts))
    frequent = {w for w, n in counts.items() if n >= 200}

    candidates: list[tuple[int, str]] = []
    typos: list[tuple[int, str, str, int]] = []
    for w in unknown:
        n = counts[w]
        if n < 3 or len(w) < 3:
            continue
        # One edit from a much-more-used word? Probable typo.
        neighbors = edits1(w) & frequent
        best = max(neighbors, key=lambda x: counts[x]) if neighbors else None
        if best and counts[best] >= TYPO_RATIO * n:
            typos.append((n, w, best, counts[best]))
        elif n >= args.threshold:
            candidates.append((n, w))

    candidates.sort(reverse=True)
    typos.sort(reverse=True)

    # ---- write the review files ----
    out_dir = library.parent
    cand_file = out_dir / "dictionary_candidates.txt"
    typo_file = out_dir / "probable_typos.txt"
    cand_file.write_text(
        "\n".join(w for _n, w in candidates) + "\n", encoding="utf-8"
    )
    typo_file.write_text(
        "\n".join(f"{w}  ->  {c}   ({n}x; correct form {cn:,}x)"
                  for n, w, c, cn in typos) + "\n", encoding="utf-8"
    )

    print(f"\nVocabulary candidates (used >= {args.threshold}x): "
          f"{len(candidates):,}  -> {cand_file}")
    print(f"Probable recurring typos: {len(typos)}  -> {typo_file}")
    print("\nTop typos to fix with the editor's staged replace (Ctrl+Shift+F):")
    for n, w, c, cn in typos[:15]:
        print(f"  {w:<20} -> {c:<18} ({n}x)")

    if args.apply:
        user_dict = Path.home() / ".wordvault" / "user_dictionary.txt"
        existing = set()
        if user_dict.exists():
            existing = {w.strip().lower()
                        for w in user_dict.read_text(encoding="utf-8").split("\n")}
        added = 0
        with open(user_dict, "a", encoding="utf-8") as fh:
            for _n, w in candidates:
                if w not in existing:
                    fh.write(w + "\n")
                    added += 1
        print(f"\nAdded {added:,} words to {user_dict}")
        print("Restart WordVault (or toggle Check Spelling) to load them.")
    else:
        print("\nReview the candidate file, then re-run with --apply to "
              "accept them into the dictionary.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

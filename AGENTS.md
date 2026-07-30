# Repository instructions

## README protection

This rule is mandatory for every future change:

- Never modify `README.md` outside the `## Download` section.
- The only permitted README changes are release-related updates inside `## Download`, such as the download link, version, and SHA-256 value.
- Preserve all README content before `## Download` and from the next level-two heading onward exactly as it is.
- Do not rewrite, translate, reformat, reorder, correct, or otherwise improve protected README content.
- Before committing any README change, inspect the diff and confirm that every changed line is located between `## Download` and the next level-two heading.

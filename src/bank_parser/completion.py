"""Shell tab-completion script generation for the ``bank-parser`` CLI.

Pure stdlib string generator: it turns the supported bank names into
deterministic ``bash`` and ``zsh`` completion scripts.  It must not import
pandas, pdfplumber or pypdf, and must not import ``argparse`` or ``banks``,
so it stays import-light and trivially testable.

The option list below must stay in sync with ``cli.build_parser()``.
"""

from __future__ import annotations

from collections.abc import Sequence

__all__ = ["SUPPORTED_SHELLS", "completion_script"]

SUPPORTED_SHELLS: tuple[str, ...] = ("bash", "zsh")

#: Options offered by the scripts; keep in sync with ``cli.build_parser()``.
_OPTIONS: str = (
    "-i --input -o --output -b --bank --detect-bank --completion "
    "--version --help"
)


def completion_script(shell: str, *, banks: Sequence[str]) -> str:
    """Return a deterministic tab-completion script for ``shell``.

    Args:
        shell: Target shell, one of :data:`SUPPORTED_SHELLS`.
        banks: Canonical bank names offered as ``--bank``/``-b`` values.

    Returns:
        The completion script as a single string with a trailing newline.

    Raises:
        ValueError: If ``shell`` is not one of :data:`SUPPORTED_SHELLS`.
    """
    if shell not in SUPPORTED_SHELLS:
        supported = ", ".join(SUPPORTED_SHELLS)
        raise ValueError(
            f"unsupported shell {shell!r}: expected one of {supported}"
        )
    if shell == "bash":
        return _bash_script(banks)
    return _zsh_script(banks)


def _bash_script(banks: Sequence[str]) -> str:
    """Build the bash ``compgen`` completion script."""
    bank_words = " ".join(banks)
    lines = [
        "# bash tab completion for bank-parser",
        "_bank_parser_completion()",
        "{",
        "    local cur prev",
        '    cur="${COMP_WORDS[COMP_CWORD]}"',
        '    prev="${COMP_WORDS[COMP_CWORD-1]}"',
        "",
        '    case "${prev}" in',
        "        -i|--input|-o|--output)",
        '            COMPREPLY=($(compgen -f -- "${cur}"))',
        "            compopt -o default 2>/dev/null",
        "            return 0",
        "            ;;",
        "        -b|--bank)",
        f'            COMPREPLY=($(compgen -W "{bank_words}" -- "${{cur}}"))',
        "            return 0",
        "            ;;",
        "        --completion)",
        '            COMPREPLY=($(compgen -W "bash zsh" -- "${cur}"))',
        "            return 0",
        "            ;;",
        "    esac",
        "",
        f'    COMPREPLY=($(compgen -W "{_OPTIONS}" -- "${{cur}}"))',
        "    return 0",
        "}",
        "complete -F _bank_parser_completion bank-parser",
    ]
    return "\n".join(lines) + "\n"


def _zsh_script(banks: Sequence[str]) -> str:
    """Build the zsh ``_arguments`` completion script."""
    bank_words = " ".join(banks)
    lines = [
        "#compdef bank-parser",
        "",
        "_bank-parser() {",
        "    local -a opts",
        "    opts=(",
        "        '-i[input bank export file]:file:_files'",
        "        '-o[output canonical CSV file]:file:_files'",
        f"        '-b[bank parser to use]:bank:({bank_words})'",
        "        '--input[input bank export file]:file:_files'",
        "        '--output[output canonical CSV file]:file:_files'",
        f"        '--bank[bank parser to use]:bank:({bank_words})'",
        "        '--detect-bank[print the detected bank name and exit]'",
        "        '--completion[print a shell completion script]:shell:(bash zsh)'",
        "        '--version[print the version and exit]'",
        "        '--help[show this help message and exit]'",
        "    )",
        '    _arguments -s -S "${opts[@]}"',
        "}",
        "",
        '_bank-parser "$@"',
    ]
    return "\n".join(lines) + "\n"

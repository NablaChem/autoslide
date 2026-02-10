import re


def format_list(content: str, process_heading_icons=None) -> str:
    """Format list content with optional heading and nested items."""
    lines = content.split("\n")
    list_lines = []

    # Check if first line is a heading (no dash)
    first_line = lines[0].strip()
    start_idx = 0

    if first_line and not first_line.startswith("-"):
        # First line is a heading
        # Handle italic formatting in heading
        first_line = re.sub(r"\*([^*]+)\*", r"\\textit{\1}", first_line)
        # Handle icon syntax in heading if processor provided
        if process_heading_icons:
            first_line = process_heading_icons(first_line)
        list_lines.append(f"\\textbf{{\\textcolor{{navyblue}}{{{first_line}}}}}")
        start_idx = 1

    # Process the list items
    list_lines.append("\\begin{itemize}")

    i = start_idx
    while i < len(lines):
        line = lines[i].strip()

        if not line:
            i += 1
            continue

        if line.startswith("-"):
            item_text = line[1:].strip()
            # Handle footnote references
            item_text = re.sub(
                r"\[\^(\d+)\]",
                r"\\footnotemark[\1]",
                item_text,
            )
            # Handle italic formatting: *text* -> \textit{text}
            item_text = re.sub(r"\*([^*]+)\*", r"\\textit{\1}", item_text)
            list_lines.append(f"\\item {item_text}")

            # Check if next lines are sub-items (indented dashes)
            sub_items = []
            j = i + 1
            while j < len(lines):
                next_line = lines[j].strip()
                if not next_line:
                    j += 1
                    continue
                # Check if it's an indented dash (starts with spaces/tabs followed by dash)
                if lines[j].startswith(("  -", "\t-", "    -")):
                    sub_item_text = next_line[1:].strip()
                    sub_item_text = re.sub(
                        r"\[\^(\d+)\]",
                        r"\\footnotemark[\1]",
                        sub_item_text,
                    )
                    # Handle italic formatting: *text* -> \textit{text}
                    sub_item_text = re.sub(
                        r"\*([^*]+)\*", r"\\textit{\1}", sub_item_text
                    )
                    sub_items.append(sub_item_text)
                    j += 1
                else:
                    break

            # Add sub-items if any
            if sub_items:
                list_lines.append("\\begin{itemize}")
                for sub_item in sub_items:
                    list_lines.append(f"\\item {sub_item}")
                list_lines.append("\\end{itemize}")

            i = j
        else:
            i += 1

    list_lines.append("\\end{itemize}")
    list_lines.append("\\vspace{0.5em}")
    return "\n".join(list_lines)
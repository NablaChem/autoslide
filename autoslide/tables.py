import re


def format_table(content: str) -> str:
    """Format markdown table content."""
    lines = [line.strip() for line in content.split("\n") if line.strip()]

    if len(lines) < 2:
        return content

    # Parse table rows
    table_rows = []
    separator_found = False

    for i, line in enumerate(lines):
        # Skip separator line (|---|---|)
        if re.match(r"^\s*\|?[\s\-\|:]+\|?\s*$", line):
            separator_found = True
            continue

        # Parse table row
        if "|" in line:
            # Remove leading/trailing pipes and split
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            # Apply italic formatting to each cell
            cells = [
                re.sub(r"\*([^*]+)\*", r"\\textit{\1}", cell) for cell in cells
            ]
            # Handle footnote references in cells
            cells = [
                re.sub(r"\[\^(\d+)\]", r"\\footnotemark[\1]", cell)
                for cell in cells
            ]
            table_rows.append(cells)

    if not table_rows:
        return content

    # Determine number of columns
    max_cols = max(len(row) for row in table_rows)

    # Build LaTeX table
    latex_lines = []
    latex_lines.append("\\begin{tabular}{" + "l" * max_cols + "}")

    for i, row in enumerate(table_rows):
        # Pad row to max columns
        padded_row = row + [""] * (max_cols - len(row))

        if i == 0:
            # Add blue line above header matching header background color
            latex_lines.append(
                "\\arrayrulecolor{ncblue!20}\\specialrule{1.33pt}{0pt}{0pt}\\arrayrulecolor{black}"
            )
            # Header row - blue background and bold text
            formatted_cells = [f"\\textbf{{{cell}}}" for cell in padded_row]
            latex_lines.append(
                "\\rowcolor{ncblue!20}" + " & ".join(formatted_cells) + " \\\\"
            )
            # Add thinner blue line under header
            latex_lines.append(
                "\\arrayrulecolor{ncblue}\\specialrule{1.33pt}{0pt}{0pt}\\arrayrulecolor{black}"
            )
        else:
            # Data rows with alternating shading pattern (2 unshaded, 2 shaded)
            # Pattern: rows 1,2 = unshaded, rows 3,4 = shaded, rows 5,6 = unshaded, etc.
            cycle_position = (i - 1) % 4  # 0,1,2,3 for rows 1,2,3,4
            if cycle_position >= 2:  # rows 3,4 in each cycle get light blue shading
                latex_lines.append(
                    "\\rowcolor{ncblue!10}" + " & ".join(padded_row) + " \\\\"
                )
            else:
                latex_lines.append(" & ".join(padded_row) + " \\\\")

    latex_lines.append("\\end{tabular}")
    return "\n".join(latex_lines)
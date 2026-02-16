def generate_header(title: str) -> str:
    """Generate LaTeX document header."""
    # Get Pygments style definitions for code highlighting
    from pygments.formatters import LatexFormatter

    pygments_style = LatexFormatter(style="default").get_style_defs()

    return (
        r"""\documentclass[aspectratio=169,t]{beamer}
% Theme and font setup
\usetheme{default}
\usepackage{graphicx}
\usepackage{fontspec}
\usefonttheme{professionalfonts} % using non standard fonts for beamer
\usefonttheme{serif} % default family is serif
\setmainfont{Fira Sans}[
  UprightFont = *-Light,
  BoldFont = *,
  ItalicFont = *-Light Italic,
  BoldItalicFont = * Italic
]
\setmonofont{Fira Mono}
\usepackage{xcolor}
\definecolor{ncorange}{RGB}{221,150,51}
\definecolor{navyblue}{RGB}{221,150,51}
\definecolor{ncblue}{RGB}{10,45,100}
\setbeamersize
{
    text margin left=0.48cm,
    text margin right=0.48cm
}
\usepackage[para]{footmisc}
\setbeamercolor{section title}{fg=navyblue}
\setbeamerfont{section title}{series=\bfseries}

\setbeamercolor{frametitle}{bg=ncblue, fg=white}
%\setbeamertemplate{frametitle}[default][left]

\setbeamertemplate{navigation symbols}{}
\setbeamertemplate{itemize item}{\textcolor{ncblue}{\textendash}}
\setbeamertemplate{itemize subitem}{\textcolor{ncblue}{\textendash}}
\setbeamertemplate{itemize subsubitem}{\textcolor{ncblue}{\textendash}}
\setlength{\leftmargini}{1em}
\setlength{\leftmarginii}{2em}
\setlength{\leftmarginiii}{3em}
\setbeamercolor{footnote mark}{fg=ncblue}
\setbeamertemplate{footnote mark}{[\insertfootnotemark]}
\setbeamertemplate{frametitle}{%
  \vskip-0.2ex
  \makebox[\paperwidth][s]{%
    \begin{beamercolorbox}[wd=\paperwidth,ht=2.5ex,dp=1ex,leftskip=1em,rightskip=1em]{frametitle}%
      \usebeamerfont{frametitle}%
      \insertframetitle\ifx\insertframetitle\@empty\else\def\tempcomma{\,}\ifx\insertframetitle\tempcomma\else\hfill{\footnotesize \insertframenumber}\fi\fi
    \end{beamercolorbox}%
  }%
  % make sure all tikz node labels only exist on the same frame
  \tikzset{tikzmark prefix=frame\insertframenumber}
}
\usepackage{amsmath}
% Set equation numbers to orange color with orange parentheses
\renewcommand{\theequation}{\textcolor{ncblue}{\arabic{equation}}}
\makeatletter
\renewcommand{\tagform@}[1]{\maketag@@@{\textcolor{ncblue}{(#1)}}}
\makeatother
\usepackage{tikz}
\usetikzlibrary{tikzmark,calc,positioning}
\pgfdeclarelayer{background}
\pgfsetlayers{background,main}
\usepackage{colortbl}
\usepackage{array}
\usepackage{booktabs}
\usepackage{fancyvrb}
\usepackage{color}
"""
        + pygments_style
        + r"""
\setlength{\parskip}{1.5em}
\setlength{\parindent}{0pt}
\setlength{\abovedisplayskip}{0pt}
\setlength{\belowdisplayskip}{0pt}
\setlength{\abovedisplayshortskip}{0pt}
\setlength{\belowdisplayshortskip}{0pt}
\begin{document}"""
    )


def generate_footer() -> str:
    """Generate LaTeX document footer."""
    return "\\end{document}"

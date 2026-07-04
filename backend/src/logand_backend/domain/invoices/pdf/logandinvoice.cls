% logandinvoice.cls -- custom LaTeX document class for logand.app's
% professional invoice PDFs. Deliberately NOT styled like the website
% (Gruvbox/monospace/glitch aesthetic) -- an invoice is a financial/legal
% document, printed and archived, not a piece of site branding, so this is
% a plain, serious, letterhead-style layout instead (see
% domain/invoices/pdf/renderer.py's doc comment for the "why LaTeX at all"
% context).
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{logandinvoice}[2026/07/01 logand.app professional invoice class]
\LoadClass[11pt,a4paper]{article}

\RequirePackage[margin=1in]{geometry}
\RequirePackage[T1]{fontenc}
% Palatino (mathpazo), not Computer Modern -- CM is the LaTeX2e default
% and reads as "typeset academic paper," which is exactly wrong for a
% financial/legal letterhead document. mathpazo ships in texlive-latex-
% base, already a transitive dependency of texlive-latex-recommended
% (see backend/Dockerfile's install list), so this needs no new package.
\RequirePackage{mathpazo}
\linespread{1.05}
\RequirePackage{xcolor}
\RequirePackage{tabularx}
\RequirePackage{booktabs}
\RequirePackage{array}
\RequirePackage{fancyhdr}
% hyperref last (standard LaTeX convention: most packages need to be
% loaded before hyperref to avoid it clobbering their own cross-reference
% hooks) -- this is what gives the ELECTRONIC copy real clickable links
% (pay-online URL, mailto: contact) while the PRINTED copy still shows the
% full literal URL text right there on the page (see \urlstyle{same} and
% \href usage in invoice.tex.jinja) -- both "printable with all
% information visible" and "PDF interactivity" at once, neither one only
% working at the expense of the other.
\RequirePackage{hyperref}

% A restrained navy/gray pair -- reads as "professional invoice," not
% "logand.app the website." Colored links print fine in black-and-white
% too (they just render as a slightly different gray), so this never
% depends on a color printer to stay legible.
\definecolor{invoiceaccent}{HTML}{1F2A44}
\definecolor{invoicegray}{HTML}{5B6472}

\hypersetup{
  colorlinks=true,
  linkcolor=invoiceaccent,
  urlcolor=invoiceaccent,
  pdfstartview=FitH,
  pdfdisplaydoctitle=true,
}
% Real URL font (not hyperref's default typewriter-ish monospace) --
% keeps a printed URL legible as normal body text rather than looking
% like a code snippet, since this class is explicitly not going for the
% website's monospace-everything look.
\urlstyle{same}

\pagestyle{fancy}
\fancyhf{}
\renewcommand{\headrulewidth}{0pt}
\renewcommand{\footrulewidth}{0.4pt}
\fancyfoot[C]{\small\color{invoicegray}Thank you for your business.\\[2pt]\thepage}

% ---- Data commands -- renderer.py's Jinja2 template calls these once,
% near the top of the document, before \begin{document}. Every value
% coming from user/admin-entered data (customer name, memo, line item
% descriptions, etc.) is LaTeX-escaped by the Python side
% (pdf/renderer.py's latex_escape()) before it ever reaches here -- this
% class assumes it's already safe LaTeX source, it does no escaping of
% its own.
\newcommand{\invoicenumber}[1]{\def\@invoicenumber{#1}}
\newcommand{\invoicedatevalue}[1]{\def\@invoicedatevalue{#1}}
\newcommand{\invoiceduedate}[1]{\def\@invoiceduedate{#1}}
\newcommand{\invoicestatus}[1]{\def\@invoicestatus{#1}}
\newcommand{\billto}[1]{\def\@billto{#1}}
\newcommand{\companyname}[1]{\def\@companyname{#1}}
\newcommand{\companydetails}[1]{\def\@companydetails{#1}}

\def\@invoicenumber{}
\def\@invoicedatevalue{}
\def\@invoiceduedate{}
\def\@invoicestatus{}
\def\@billto{}
\def\@companyname{}
\def\@companydetails{}

% ---- Layout commands

% \\[Npt] used directly after a minipage (or between two minipages with
% no intervening \par) is invalid -- \\ is only meaningful inside a
% paragraph already in vertical mode, and immediately-adjacent box
% material isn't one. That's what "There's no line here to end" meant
% (confirmed against a real compile, not assumed) -- every gap below
% is \par\vspace{...} instead, and the divider rule is \rule{}{} (a real
% LaTeX box), not the low-level TeX \hrule primitive, for the same
% "needs to already be in a paragraph" reason.
\newcommand{\invoiceheader}{%
  \noindent
  \begin{minipage}[t]{0.55\textwidth}
    {\LARGE\bfseries\color{invoiceaccent}\@companyname}\par\vspace{6pt}
    {\small\color{invoicegray}\@companydetails}
  \end{minipage}%
  \hfill
  \begin{minipage}[t]{0.4\textwidth}
    \raggedleft
    {\Large\bfseries\color{invoiceaccent}INVOICE}\par\vspace{8pt}
    % Invoice numbers are UUIDs (see domain/invoices/pdf/renderer.py's
    % build_invoice_pdf_data), too long to fit an `l` (unbounded, no-
    % wrap) column on one line without running off the page margin
    % (confirmed against a real compile). A fixed-width, right-aligned
    % p{} column lets it wrap onto a second line inside its own cell
    % instead of overflowing.
    \begin{tabular}{@{}r >{\raggedleft\arraybackslash}p{4.4cm}@{}}
      \textbf{Invoice \#:} & \small\@invoicenumber \\
      \textbf{Date:} & \@invoicedatevalue \\
      \textbf{Due:} & \@invoiceduedate \\
      \textbf{Status:} & \@invoicestatus \\
    \end{tabular}
  \end{minipage}
  \par\vspace{18pt}
  \noindent{\color{invoiceaccent}\rule{\linewidth}{1.2pt}}
  \par\vspace{14pt}
}

\newcommand{\billtoblock}{%
  \textbf{\color{invoiceaccent}Bill To}\par\vspace{2pt}
  \@billto\par\vspace{16pt}
}

% Deliberately NOT a \newenvironment wrapping tabularx (tried first) --
% tabularx captures its own body via an internal macro that scans for a
% literal, textually-adjacent \end{tabularx}, and wrapping it inside
% \newenvironment's begin/end code broke that scan ("Runaway argument?
% File ended while scanning use of \TX@get@body", confirmed against a
% real compile, not assumed) regardless of what was actually in the
% table. \invoicetableheader just emits the header row; the template
% writes \begin{tabularx}...\end{tabularx} directly around it and the
% line-item rows, so tabularx always sees its own real \begin/\end pair
% with nothing else expanding in between.
\newcommand{\invoicetableheader}{%
  \toprule
  \textbf{Description} & \textbf{Qty} & \textbf{Unit Price} & \textbf{Amount} \\
  \midrule
}

\newcommand{\invoicetotals}[1]{%
  \vspace{10pt}
  \begin{flushright}
    #1
  \end{flushright}
}

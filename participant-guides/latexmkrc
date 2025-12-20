#!/usr/bin/env perl

# LaTeX Makefile configuration for latexmk
# This file configures how LaTeX documents are compiled

# Use pdflatex as the PDF generator
$pdf_mode = 1;
$postscript_mode = 0;
$dvi_mode = 0;

# Output auxiliary files to build/ directory to keep root clean
# PDFs are copied to root after compilation
$aux_dir = 'build';
$out_dir = 'build';

# Copy PDF to root directory after successful compilation
$success_cmd = 'cp %D ./';

# Set pdflatex executable
$pdflatex = 'pdflatex -shell-escape -interaction=nonstopmode %O %S';

# PDF viewer - uncomment the appropriate line for your system
# macOS:
$pdf_previewer = 'open -a Preview %O %S';
# Alternatively for macOS with Skim:
# $pdf_previewer = 'open -a Skim %O %S';

# Enable file change tracking (watches for changes and recompiles automatically)
$recorder = 1;

# Set the number of times to run LaTeX
$max_repeat = 5;

# Ensure that auxiliary files are cleaned up properly
push @generated_exts, 'synctex.gz';

# File extensions to clean when running 'latexmk -c'
@clean_ext = qw(aux out bbl blg fls fdb_latexmk);

# Verbose output
$verbose = 0;

# Documentation Translation Instructions

## Overview

This project includes a translation script to update the piTantum timetable system documentation in both Italian and English languages.

## Files

- `translate_documentation.py` - Main translation script
- `manual.pdf` (Italian) and `manual_en.pdf` (English) - Built documentation

## Translation Process

The translation process involves:

1. **Parsing LaTeX source files** - Extracting content sections
2. **Translation using Qwen Turbo model** - Translating technical content  
3. **Rebuilding PDF documentation** - Generating updated documents

## Prerequisites

To run the translation:

1. **LaTeX installation** - Required for PDF generation
2. **Qwen Turbo API access** - For actual translation capability
3. **Python 3.8+** - Required for the translation script

## Usage

```bash
# Run the translation script (conceptual)
python translate_documentation.py
```

## Implementation Details

The translation system handles:

- **Technical terminology** - Educational scheduling domain terms
- **LaTeX structure preservation** - Figures, tables, cross-references
- **Multi-language support** - Italian to English and vice versa
- **Build automation** - Integration with existing build scripts

## Limitations

1. **Qwen Turbo integration** - Requires API key and proper setup
2. **Technical accuracy** - Translation of scheduling constraints needs domain expertise
3. **PDF generation** - Requires LaTeX toolchain to rebuild properly

## Building Documentation

To rebuild the documentation after translation:

```bash
# For Italian manual (manual.pdf)
cd docs/
./build_manual.sh

# For English manual (manual_en.pdf) 
cd docs/
./build_manual.sh --english
```

## Current Status

The translation framework is ready but requires actual integration with Qwen Turbo API for real translation to occur. The system provides:

- Conceptual translation pipeline
- LaTeX document structure handling  
- Multi-language support infrastructure
- Build process automation

## Contributing

Translations should be reviewed by domain experts to ensure technical accuracy in the Italian and English scheduling contexts.
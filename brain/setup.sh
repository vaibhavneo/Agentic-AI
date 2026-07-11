#!/bin/bash
# Setup script for Agentic AI Brain

echo "⚡ Setting up Agentic AI Brain..."

# Install required packages
pip install anthropic 2>/dev/null || pip3 install anthropic

echo ""
echo "✅ Dependencies installed."
echo ""
echo "Next: Set your API key and run:"
echo ""
echo "  export ANTHROPIC_API_KEY=sk-ant-..."
echo "  python3 cli.py"
echo ""
echo "Or single task:"
echo "  python3 cli.py 'Research the latest in agentic AI'"

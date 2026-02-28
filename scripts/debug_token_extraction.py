#!/usr/bin/env python3
import re

# Test on composite log
composite_log = "results/localization_composite_score_sympy10_20251104/localization_logs/sympy__sympy-13043.log"
baseline_log = "results/localization_base_sympy10_20251103/localization_logs/sympy__sympy-13043.log"

def extract_tokens_debug(log_file, name):
    print(f"\n{'='*80}")
    print(f"DEBUG: {name}")
    print(f"{'='*80}")
    
    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    
    # Find ALL matches
    matches = list(re.finditer(r"'prompt_tokens':\s*(\d+)", content))
    
    print(f"Total 'prompt_tokens' matches: {len(matches)}")
    print()
    
    for i, match in enumerate(matches):
        token_value = int(match.group(1))
        # Get surrounding context
        start = max(0, match.start() - 100)
        end = min(len(content), match.end() + 50)
        context = content[start:end]
        
        # Simplify context for readability
        context = context.replace('\n', ' ').strip()
        
        print(f"Match {i+1}: {token_value:,} tokens")
        print(f"  Context: ...{context}...")
        print()
    
    print(f"First match: {int(matches[0].group(1)):,} tokens")
    print(f"Last match: {int(matches[-1].group(1)):,} tokens")

extract_tokens_debug(composite_log, "COMPOSITE")
extract_tokens_debug(baseline_log, "BASELINE")

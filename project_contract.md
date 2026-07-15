Contract:
Project loader
- Takes: the directory
- Returns: file paths, import list, roots, and tests
Analysis:
- Takes: file paths
- Returns file Asts, hotspots
Context Builder:
- Takes: file with the highest score
- Returns: candidates
Evaluator:
- Takes: candidates
- Returns: final file
Benchmark:
- Takes: final project
- Retruns: benchmark report and diff report

# Evaluation contract — concept_map (recreation)
## MUST
- **E1 fixture ground truth**: on a 3-concept fixture with known relationships and a 0.6 floor, output matches hand-computed nodes/edges exactly.
- **E2 negative control**: nonsense name_contains => n=0, edges=[] (honest empty, not error); absent store => same.
- **E3 invariant/bounds**: no dangling edges on the LIVE store at floors {0, 0.6, 0.95}; n == len(nodes); confidences within [0,1].
## Discrimination
E1 catches wrong filter comparisons (> vs >=); E3 catches keeping edges to filtered-out nodes (the obvious wrong impl builds edges before filtering).

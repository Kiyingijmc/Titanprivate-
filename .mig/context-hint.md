TOKEN OPTIMIZATION — a knowledge graph of this repo exists at graphify-out/graph.json.
BEFORE grepping or reading whole files:
  1. If the `graphify` CLI is available, prefer: graphify query "<question>" ·
     graphify path "<A>" "<B>" · graphify explain "<entity>".
  2. Else query graphify-out/graph.json with jq to locate entities/relations,
     then read ONLY the files/sections it points to.
  3. Fall back to grep/read only when the graph lacks the answer.
The graph may be slightly stale vs. the working tree — trust the tree when they disagree.

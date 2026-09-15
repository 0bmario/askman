# Better Askman release gate

`retrieval-v2` is promoted as the Better Askman only when it is a Pareto improvement over `main`: higher paired top-result success across at least two scenario families, no regression in top-three success, incorrect or false answers, platform behavior, or offline operation, acceptable resource performance, and reproducible evidence from pinned inputs. This gate favors a credible, resume-quality engineering result over an unsupported aggregate benchmark win.

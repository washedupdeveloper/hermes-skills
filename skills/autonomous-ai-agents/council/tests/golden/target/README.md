# Golden fixture target

Not a real project. It exists so the golden suite has a **fixed** target to score:
a stable `kloc` and a stable stack detection, so a pinned score means something.

`README.md` is deliberately `.md` — not a source suffix — so it does not enter `kloc`.

Do not add code here to make it "more realistic". Every line changes every pinned
number in `../expect.json`, and a fixture that drifts is a fixture that gets
regenerated without anyone reading the diff.

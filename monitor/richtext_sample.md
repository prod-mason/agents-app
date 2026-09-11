**Clip 2.0 HQ now runs under Rosetta at 48%, down from 252%.** 🎉

## What changed
The fix is ==automatic==, needs ++no setting++, and the old ~~manual toggle~~ is gone. *Italic* and _italic_ both work, `code with **stars**` stays literal, and a family 👨‍👩‍👧‍👦 plus a thumbs up 👍🏽 survive untouched.

| Build | CPU | Result |
|---|:-:|--:|
| Native | 16% | **pass** |
| Rosetta, old | 252% | ==stutters== |
| Rosetta, fixed | 48% | pass ✅ |

1. **Time the whole plugin**, not just the engine.
   - under Rosetta
   - native, as a control
2. Ship after the Pro Tools lane's builds.

> A quote from the lane: *the sound did not change*, bit for bit.

```python
def gain(x):
    if x > 1.0:
        return 1.0   # indentation kept
    return x
```

Hostile text stays text: <script>alert(1)</script> <img src=x onerror=alert(1)> and [a bad link](javascript:alert(1)). A [good link](https://developer.apple.com) is underlined.

# PR Review — feature/x vs main

**Commit:** `aaaaaaaaaaaa` (HEAD) ← `bbbbbbbbbbbb` (main)
**Generated:** 2026-05-07T14:32:19+00:00 · **Model:** anthropic:claude-sonnet-4-6 · **Duration:** 3.21s

## Summary

| Severity | Bugs | Rule violations | Total |
|---|---|---|---|
| blocker | 1 | 0 | 1 |
| high    | 0 | 1 | 1 |
| medium  | 0 | 0 | 0 |
| low     | 0 | 0 | 0 |

Rules loaded: `no-class-components`, `prefer-pure-functions`

## Blocker

### `src/x.py:42-42` — null deref

**Evidence:**

````diff
+    return user_data.name
````

**Category:** bug

x may be None here.

---

## High

### `src/components/X.tsx:1-20` — class component used

**Evidence:**

````diff
+class UserProfile extends React.Component {
+  render() {
+    return <div>...</div>;
+  }
+}
````

**Category:** project_rule (`no-class-components`)

Convert to functional.

**Suggested fix:**

> use hooks

---

_Tokens: in=1234, out=567_

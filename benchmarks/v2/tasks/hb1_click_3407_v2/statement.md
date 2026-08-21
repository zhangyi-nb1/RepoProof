# pallets/click PR #3407: `click.prompt` typing clarifications / improvements

merged_at: 2026-07-22T22:25:17Z
merge_commit: 5e906a8afb67242dffdd91404dbf31f469054b15
base: cfa01eeb7894a408af70b29d28c0b24f8680f9fb

## PR 正文

This improves the typing of `click.prompt`. However there is still an opening question / issue...

# Brief summary

The current code makes the following change to the public API of `click.prompt`:

```diff
 def prompt(
     text: str,
-    default: t.Any | None = None,
+    default: V | None = None,
     hide_input: bool = False,
     confirmation_prompt: bool | str = False,
-    type: ParamType[t.Any] | t.Any | None = None,
-    value_proc: t.Callable[[str], t.Any] | None = None,
+    type: ParamType[V] | V | None = None,
+    value_proc: t.Callable[[str], V] | None = None,
     prompt_suffix: str = ": ",
     show_default: bool | str = True,
     err: bool = False,
     show_choices: bool = True,
-) -> t.Any:
+) -> V:
````

This changes the behaviour in that you can no longer pass types that aren't the same type as the type you expect at the end. For example:

```python
click.prompt("Iteration amount?", default="100", type=int)
```

Would no longer work under the current implementation because `"100"` is not of the type `int`. In the old implementation this worked because default values still were passed as `int("100")` before being returned. The remaining question is then what behaviour we should go for.

You could say, "why" not keep the current implementation? Well we could, but it's not actually typed correctly and actually allows behaviour we don't account for. That behaviour is that `value_proc: t.Callable[[str], V] | None = None` accepts only `str` to convert to the target type. So technically you shouldn't be allowed to pass `Any` to it. However.... `ParamType.__call__`, which makes `ParamType` also a callable, is used to convert the `default` to the target `type` as well and that accepts `Any`, not `str`. So there's not really a strict contract anywhere.

To make the decision on this PR easier I propose the following options:

## 1. Restrict `default` to same type (current implementation)

- Accept only the same type as the type passed in `type` in `default`.
- DO NOT pass `default` to `value_proc` or the constructor of `type`.

```diff
 def prompt(
     text: str,
-    default: t.Any | None = None,
+    default: V | None = None,
     hide_input: bool = False,
     confirmation_prompt: bool | str = False,
-    type: ParamType[t.Any] | t.Any | None = None,
-    value_proc: t.Callable[[str], t.Any] | None = None,
+    type: ParamType[V] | V | None = None,
+    value_proc: t.Callable[[str], V] | None = None,
     prompt_suffix: str = ": ",
     show_default: bool | str = True,
     err: bool = False,
     show_choices: bool = True,
-) -> t.Any:
+) -> V:
````


## 2. Public API typing change (or correction) with unlikely users

- Accept the same type as the type passed in `type` in `default` and also `str`.
- If `default` type is different from the type of `type`, pass it to `value_proc` or the constructor of `type` to convert it.
	- Make `ParamType.__call__` also onyl accept `str`, not `Any`.

```diff
 def prompt(
     text: str,
-    default: t.Any | None = None,
+    default: V | str | None = None,
     hide_input: bool = False,
     confirmation_prompt: bool | str = False,
-    type: ParamType[t.Any] | t.Any | None = None,
-    value_proc: t.Callable[[str], t.Any] | None = None,
+    type: ParamType[V] | V | None = None,
+    value_proc: t.Callable[[str], V] | None = None,
     prompt_suffix: str = ": ",
     show_default: bool | str = True,
     err: bool = False,
     show_choices: bool = True,
-) -> t.Any:
+) -> V:
````

```diff
    @t.overload
    def __call__(
        self,
        value: None,
        param: Parameter | None = None,
        ctx: Context | None = None,
    ) -> None: ...

    @t.overload
    def __call__(
        self,
-       value: t.Any,
+       value: str,
        param: Parameter | None = None,
        ctx: Context | None = None,
    ) -> ParamTypeValue: ...

    def __call__(
        self,
-       value: t.Any,
+       value: str,
        param: Parameter | None = None,
        ctx: Context | None = None,
    ) -> ParamTypeValue | None:
        if value is not None:
            return self.convert(value, param, ctx)
        return None

    def convert(
        self,
-       value: t.Any,
+       value: str,
		param: Parameter | None,
		ctx: Context | None,
    ) -> ParamTypeValue:

```


## 3. Change `value_proc` to accept `Any`

- Accept `Any` in `default`, keeping the same accepted type as before.
- If `default` type is different from the type of `type`, pass it to `value_proc` or the constructor of `type` to convert it.

```diff
 def prompt(
     text: str,
-    default: t.Any | None = None,
+    default: V | t.Any | None = None,
     hide_input: bool = False,
     confirmation_prompt: bool | str = False,
-    type: ParamType[t.Any] | t.Any | None = None,
-    value_proc: t.Callable[[str], t.Any] | None = None,
+    type: ParamType[V] | V | None = None,
+    value_proc: t.Callable[[t.Any], V] | None = None,
     prompt_suffix: str = ": ",
     show_default: bool | str = True,
     err: bool = False,
     show_choices: bool = True,
-) -> t.Any:
+) -> V:
````

# My preference?

Even though I've implemented the first option, I think the second option makes the most sense. I don't think there's a usecase for accepting beyond `str` for parsing.



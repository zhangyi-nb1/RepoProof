# pallets/click PR #3581: Add `@custom_version_option`, freeze `@version_option`

merged_at: 2026-07-08T03:26:28Z
merge_commit: 94c191ca6c9598865fc5672b85cf138845b337d5
base: 16fc00e2f4a2717a521084f193709a6058afc693

## PR 正文

This is an attempt to address the design discussion we started in #3527 about `@version_option` extensibility.

What's in this PR:
- A `.. note::` admonition to point to `@version_option` freeze.
- A new `@custom_version_option` that mirrors `@help_option` and `@version_option` and takes a callback for a custom message.

I did not take the class-based approach here, as it reminded me of the `HelpOption` class that I was too fast to add in #2563 (v8.1.8) then had to remove in #2832/#2840 (v8.2.0).

If I like the explicitness of the freeze admonition, I don't like the rest of the code: the naming of `@custom_version_option` and the apparent duplication with `@version_option`. But I produced this PR anyway to explore the effect of our policy and to have a concrete example to discuss.



## 关联 issue #2832: Regression: Help option subclassing no longer works with verion 8.1.8 

Click 8.18 has a regression wrt. to help with Option subclasses.

This was found in this issue originally:
- https://github.com/aboutcode-org/scancode-toolkit/issues/4044

This was introduced in this PR by @kdeldycke :wave: :
- https://github.com/pallets/click/pull/2563

It breaks code that uses option subclasses. 


- This code works in 8.1.7 and  8.1.8 with no custom class
```Python
import click

@click.command()
@click.help_option("-h", "--help")
def scancode():
    """OK in pkg:pypi/click@8.1.8 and pkg:pypi/click@8.1.7"""
    pass


if __name__ == "__main__":
    scancode()
```
and then with 8.1.7 and 8.1.8:
```
$ python  works.py --help
Usage: works.py [OPTIONS]

  Regression in pkg:pypi/click@8.1.8

Options:
  -h, --help  Show this message and exit.
```




- This code works in 8.1.7 and fails in 8.1.8 with a custom class
```Python
import click


class PluggableCommandLineOption(click.Option):
    pass


@click.command()
@click.help_option("-h", "--help", cls=PluggableCommandLineOption)
def scancode():
    """Regression in pkg:pypi/click@8.1.8"""
    pass


if __name__ == "__main__":
    scancode()
```

and then with 8.1.7
```
 python  failing.py --help
Usage: failing.py [OPTIONS]

  Regression in pkg:pypi/click@8.1.8

Options:
  -h, --help  Show this message and exit.


$ python  failing.py -h
Usage: failing.py [OPTIONS]

  Regression in pkg:pypi/click@8.1.8

Options:
  -h, --help  Show this message and exit.

```

and then with 8.1.8
```
$ python  failing.py -h
Error: Option '-h' requires an argument.


$ python  failing.py --help
Error: Option '--help' requires an argument.


```



- This code works more or less in 8.1.7 and 8.1.8 with custom class and no "--help" option
```Python
import click


class PluggableCommandLineOption(click.Option):
    pass


@click.command()
@click.help_option("-h", cls=PluggableCommandLineOption)
def scancode():
    """Regression in pkg:pypi/click@8.1.8"""
    pass


if __name__ == "__main__":
    scancode()

```
and then with 8.1.7
```
$ python  works2.py -h
Usage: works2.py [OPTIONS]

  Regression in pkg:pypi/click@8.1.8

Options:
  -h      Show this message and exit.
  --help  Show this message and exit.
```

and then with 8.1.7
```
$ python  works2.py --help
Usage: works2.py [OPTIONS]

  Regression in pkg:pypi/click@8.1.8

Options:
  -h      Show this message and exit.
  --help  Show this message and exit
```

and then with 8.1.8
```
$ python  works2.py -h
Error: Option '-h' requires an argument.

```
and then with 8.1.8 note the changes in `-h TEXT`
```
$ python  works2.py --help
Usage: works2.py [OPTIONS]

  Regression in pkg:pypi/click@8.1.8

Options:
  -h TEXT
  --help   Show this message and exit.

```





Environment:

- Python version: 3.9 to 3.11
- Click version: 8.1.8


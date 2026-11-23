---
name: python-docstrings
description: Format and write Google-style docstrings for Python code compatible with mkdocstrings. Use whenever writing, generating, documenting, or modifying Python functions, classes, or modules.
metadata:
  version: 2026-11-20
---

# Python Docstring Guidelines

Generate Google-style docstrings formatted for compatibility with `mkdocstrings`. Write in American English using ASCII characters only. The target audience includes domain scientists and general software developers.

Many readers are non-native English speakers, and they may read the docs in a notebook. Write so that they understand each docstring on the first read, without reading the code.

If the project has its own docstring conventions, follow them where they differ from these rules.

## Formatting Rules & Code References
- Use backticks for names from the code and for types, for example `table`, `normalize()`, `Qtable` or `pd.DataFrame`.
- Write a string value, including a column name, in single quotes inside backticks, for example `'mean'` or `'Protein'`. Write a parameter setting in assignment format, for example `style='proquant-notebook'`.
- Write `True`, `False`, `None` and numbers without backticks, except inside an assignment.
- Use a raw docstring (`r"""`) if the docstring contains a backslash.
- Put a blank line before a list, because Python-Markdown does not render a list that directly follows a paragraph.

## Section Structure & Order
1. **Summary line**: See "Writing Style".
2. **Body**: Explanation of the functionality or context, if not obvious from the summary line. State important assumptions, limitations and non-obvious behavior, for example that the intensities must be log-transformed.
3. **Warning** *(Rare)*: Use only for surprising behavior that can cause data loss or silently wrong results, for example silently dropping rows. Do not use it for obvious or intended behavior. Write `Warning:` (singular; `Warnings:` is a different section) on its own line, followed by an indented block.
4. **Args** (followed by **Attributes** for classes): Parameter descriptions formatted per default-value rules.
5. **Returns** (or **Yields** for generators): Describe the return value: what it contains and what it means. Do not repeat the type from the return annotation. Omit `Returns` if the function returns None.
6. **Raises**: Exceptions raised and their triggers.
7. **Examples** *(Conditional)*: Include only for primary high-level public API functions and for functions where extra context is useful, not for trivial functions.
   - Use `>>>` doctest style only when the output is predictable and the snippet can actually be executed (i.e., a doctest would pass). Do not use "imagined" or mock inputs that cannot run.
   - Use a fenced code block otherwise.

## Classes
- Write the class description, the `__init__` arguments (`Args`) and the public attributes (`Attributes`) in the class docstring.
- Do not write a docstring for `__init__`.

## Default Value Description Rules in `Args`
- **For `bool`**: Describe what True does, then state the default in a trailing sentence. Describe the False case only if it is not obvious, for example with "Otherwise, ...". Prefer this pattern, but write a natural sentence if the pattern reads awkwardly, and keep the trailing default sentence:
   - Example: ``If True, adds the prefix `'Expression'` to each column name. Defaults to False.``
   - Example: `If True, removes the rows with missing values. Otherwise, replaces the missing values with 0. Defaults to True.`
- **For `None` with fallback behavior**: Add a conditional sentence that states the fallback:
   - Example: `Columns to summarize. If None (default), uses all sample columns.`
- **For `None` that only means "not used"**: Use a trailing sentence if the effect of None is obvious. Otherwise, use the fallback form above:
   - Example: `Title of the plot. Defaults to None.`
- **For specific scalar values**: Use an explicit trailing sentence:
   - Example: `Maximum number of retries for a request. Defaults to 3.`
   - Example: ``Summary statistic, either `'mean'` or `'median'`. Defaults to `'mean'`.``

## Writing Style

### Summary line
- Write one sentence that adds information beyond the function name. You can use the words of the name, for example "Normalize the intensities to the median of each sample" for `normalize_intensities()`.
- Use the imperative mood, for example "Return the mean", not "Returns the mean". For classes, modules and properties, use a noun phrase.
- Use an exact verb, for example "Return", "Check", "Raise", "Convert". Do not use vague verbs such as "Handle", "Manage" or "Make sure".

### Sentences and words
These rules apply to the body and to all section entries.
- Write one main idea in each sentence. Keep sentences short, and split a sentence that contains two ideas.
- Keep a reason in the same sentence as its fact, for example with "because" or "so that".
- Use the present tense. Prefer the active voice, but use the passive if it is more natural, for example "the rows that are kept".
- In the body and in `Args`, use the third person for what the function does, for example "Removes rows with missing values". The function is the default subject, so do not start each sentence with "This function". For an action that the caller must take, use the imperative or "you", for example "Provide a table with one row per peptide".
- Use one term for one concept, and do not use synonyms. Follow the project conventions if they are known, and use the same terms as the other docstrings of the project.
- Avoid long noun chains. Split them with a preposition, for example "the score of the peptide match". Do not remove articles ("the", "a").
- Keep short enumerations in the sentence. Use a bullet list for conditions or rules that the reader scans or compares. Use a numbered list for ordered steps, with one action in each step.
- Use common words. Use a technical term when it is the correct name, for example "validate", "in place", or "non-finite".
- Replace quality words ("flexible", "efficient", "robust") with facts. Do not use filler words ("simply", "easily", "note that").

### Args, Returns and Raises
- Write each `Args` and `Attributes` entry as `name: description`, without a type, because mkdocstrings takes the types from the annotations.
- Prefer to start a description with a noun phrase that says what the argument is, except for `bool` arguments (see the default-value rules). These are preferences, not fixed sentence patterns: if another start reads more naturally, use natural and concise language.
- For a table argument or return value, describe the layout, for example one row per protein. For an argument, also name the data that the caller must provide, for example the required columns.
- In `Raises`, write one entry for each cause. The same exception can occur in more than one entry.
- Document the exceptions that a caller can trigger. Do not list exceptions that you cannot trace in the code.

## Check

- Compare the docstring with the code and make sure that the docstring is correct.
- Change only the docstrings of code that you add or modify, unless you are asked to do more.
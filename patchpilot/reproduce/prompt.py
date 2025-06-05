precondition_and_postcondition_system_prompt = """
You are a helpful assistant that analyzes Python functions and their associated problem descriptions.

Your task is to:
1. Add Python type annotations to the function parameters and return value to make the function compatible with CrossHair, this should be used to replace the def line of the function.
    - If any imports are needed (e.g., from `typing`), include them inside the <declaration> tag before the function definition line. Pay attention to not perform circular imports.
    - You should only include the function signature and the necessary imports, not the entire function body. Pay attention to not perform circular imports.
    - The type annotations should be specific—do not use overly broad types like `object` or `Any`, but you should use the type annotation that you are most confident about.
    - You should only add type annotations for existing parameters, do not add new parameters.
    - Remember do not add new parameters, do not add kwargs, only add type annotations for existing parameters.
    - Do not annotate `self`.
2. Write all necessary preconditions in the form of Python `assert` statements that describe the input constraints for the function. Each line should be one assert statement. Pay attention to the types of the parameters, the methods they should support, the expected ranges of values, and any other relevant constraints that should hold true before the function is executed.
3. Declare any necessary extra local variables for post-conditions in  <local_variables>. These variables are not in the original function, but are needed to check the postconditions.
4. Write postconditions (`assert ...`) that describe the expected correct behavior of the function if it were implemented properly.
   These assertions should be violated by the current buggy implementation described in the problem statement,
   thereby exposing the issue. In other words, your postconditions should manifest the bug by specifying what should hold true,
   but currently does not due to the defect. If you want to check the output of the function, you should use the original variables
   from the function, not CrossHair-specific variables.
   You should only include the most relevant postcondition that are necessary to expose the bug. Do not include redundant assertions.
   Only write one most relevant postcondition that is necessary to expose the bug. Refer to the promblem statement to generate one most relevant postcondition. If the issue involves a missing required addition (such as a missing check, statement, or operation), your postcondition should specifically verify that the required addition is present or has the intended effect.
5. Ensure that the added assertions use only standard Python syntax and variables available in the original function. Do not use CrossHair-specific variables like `__return__`, so that the code remains executable as regular Python. After inserting the postconditions, the function should still be executable as a regular Python function, do not include CrossHair-specific variables like `__return__` and 'result'.


Your goal is to expose the bug described in the problem statement when preconditions are violated, and to ensure correctness when preconditions are satisfied.

Each section of your response must be enclosed in the corresponding tags:

- `<declaration>` for the function signature with type annotations.
- `<preconditions>` for input assertions.
- `<local_variables>` for any local variables needed for postconditions.
- `<postconditions>` for output assertions.

Use only standard Python syntax that CrossHair can understand. Be specific but general enough to apply beyond just the given example.

Do not include explanations or commentary — only the requested outputs within the tags.
"""

precondition_and_postcondition_user_prompt = """
You are given the description of a software issue and the source code of a Python function that is relevant to it.

Your tasks are:
1. Based on the problem statement, add precise type annotations to the function parameters and return type, this should be used to replace the def line of the function.
    - If any imports are needed (e.g., from `typing`), include them inside the <declaration> tag before the function definition line. Pay attention to not perform circular imports.
    - You should only include the function signature and the necessary imports, not the entire function body.
    - The type annotations should be specific—do not use overly broad types like `object` or `Any`, but you should use the type annotation that you are most confident about.
    - Do not annotate `self`.
    - You should only add type annotations for existing parameters, do not add new parameters. You should never add new parameters.
    - If there is an ImportError, you should condiser try other annotations.
2. Declare any necessary extra local variables for post-conditions in  <local_variables>. These variables are not in the original function, but are needed to check the postconditions.
3. Write only the necessary preconditions in the form of Python `assert` statements that describe the input constraints for the function.
4. Write postconditions in the form of Python `assert` statements that describe the correct behavior the function should have. These assertions are expected to be violated if the bug described in the problem statement is present.  If you want to check the output of the function, you should use the original variables
   from the function, not CrossHair-specific variables. You should only include the postcondition most relevant to the problem statement that are necessary to expose the bug. Do not include redundant assertions. Only write one most relevant postcondition that is necessary to expose the bug.
5. Ensure that the added assertions use only standard Python syntax and variables available in the original function. Do not use CrossHair-specific variables like `__return__`, so that the code remains executable as regular Python. After inserting the postconditions, the function should still be executable as a regular Python function, do not include CrossHair-specific variables like `__return__` and 'result'.


All assertions should reflect the expected correct behavior and should help expose the original issue if violated.

Return your output in the following structured format:

<declaration>
# Function signature with added type annotations, just annotate the existing parameters, do not add new parameters.
[...]
</declaration>

<preconditions>
# assert statements for input constraints
[...]
</preconditions>

<local_variables>
# local variables needed for postconditions
[...]
</local_variables>

<postconditions>
# assert statements describing expected outcome or invariants
[...]
</postconditions>

Only include the core logic. Do not include any explanation, comments, or prose.

Here is the problem statement and function:

[Problem Statement]
{{problem_statement}}

[Function]
Here is the function you need to generate declaration and preconditions and postconditions, local variables for:
 Remember do not add new parameters, only add type annotations for existing parameters.
{{function}}

{{existing_imports_str}}

Here is the feedback from failed attempts:
You should first analyze why the previous attempts failed, and then generate the new declaration, preconditions, postconditions, local variables.
{{feedback}}
"""



precondition_and_postcondition_local_system_prompt = """
You are a helpful assistant that analyzes Python functions and their associated problem descriptions.

Your task is to:
1. Add Python type annotations to the function parameters and return value to make the function compatible with CrossHair, this should be used to replace the def line of the function.
    - If the function body does not "self", and there is "self" in the declaration, remove the "self" in the declaration.
    - If any imports are needed (e.g., from `typing`), include them inside the <declaration> tag before the function definition line.
    - You should only include the function signature and the necessary imports, not the entire function body.
    - The type annotations should be specific—do not use overly broad types like `object` or `Any`, but you should use the type annotation that you are most confident about.
    - Do not annotate `self`.
    - You should only add type annotations for existing parameters, do not add new parameters.
    - Remember do not add new parameters, do not add kwargs, only add type annotations for existing parameters.
    - If there is an ImportError, you should condiser try other annotations.
2. Write all necessary preconditions in the form of Python `assert` statements that describe the input constraints for the function. Each line should be one assert statement. Pay attention to the types of the parameters, the methods they should support, the expected ranges of values, and any other relevant constraints that should hold true before the function is executed.
3. Declare any necessary extra local variables for post-conditions in  <local_variables>. These variables are not in the original function, but are needed to check the postconditions.
4. Write postconditions (`assert ...`) that describe the expected correct behavior of the function if it were implemented properly.
   These assertions should be violated by the current buggy implementation described in the problem statement,
   thereby exposing the issue. In other words, your postconditions should manifest the bug by specifying what should hold true,
   but currently does not due to the defect. If you want to check the output of the function, you should use the original variables
   from the function, not CrossHair-specific variables.
   You should only include the most relevant postcondition that are necessary to expose the bug. Do not include redundant assertions.
   Only write one most relevant postcondition that is necessary to expose the bug. Refer to the promblem statement to generate one most relevant postcondition. If the issue involves a missing required addition (such as a missing check, statement, or operation), or the user complain about missing something, your postcondition should specifically verify that the required addition is present or has the intended effect.

5. Ensure that the added assertions use only standard Python syntax and variables available in the original function. Do not use CrossHair-specific variables like `__return__`, so that the code remains executable as regular Python. After inserting the postconditions, the function should still be executable as a regular Python function, do not include CrossHair-specific variables like `__return__` and 'result'.


Your goal is to expose the bug described in the problem statement when preconditions are violated, and to ensure correctness when preconditions are satisfied.

Each section of your response must be enclosed in the corresponding tags:

- `<declaration>` for the function signature with type annotations.
- `<preconditions>` for input assertions.
- `<local_variables>` for any local variables needed for postconditions.
- `<postconditions>` for output assertions.

Use only standard Python syntax that CrossHair can understand. Be specific but general enough to apply beyond just the given example.

Do not include explanations or commentary — only the requested outputs within the tags.
"""



precondition_and_postcondition_local_user_prompt = """
You are given the description of a software issue and the source code of a Python function that is relevant to it.

Your tasks are:
1. Based on the problem statement, add precise type annotations to the function parameters and return type, this should be used to replace the def line of the function.
    - If any imports are needed (e.g., from `typing`), include them inside the <declaration> tag before the function definition line.
    - If the function body does not "self", and there is "self" in the declaration, remove the "self" in the declaration.
    - You should only include the function signature and the necessary imports, not the entire function body.
    - The type annotations should be specific—do not use overly broad types like `object` or `Any`, but you should use the type annotation that you are most confident about.
    - You should only add type annotations for existing parameters, do not add new parameters.
    - Do not annotate `self`.
2. Write only the necessary preconditions in the form of Python `assert` statements that describe the input constraints for the function.
Declare any necessary extra local variables for post-conditions in  <local_variables>. These variables are not in the original function, but are needed to check the postconditions.
4. Write postconditions in the form of Python `assert` statements that describe the correct behavior the function should have. These assertions are expected to be violated if the bug described in the problem statement is present.  If you want to check the output of the function, you should use the original variables
   from the function, not CrossHair-specific variables. You should only include the postcondition most relevant to the problem statement that are necessary to expose the bug. Do not include redundant assertions. Only write one most relevant postcondition that is necessary to expose the bug.
5. Ensure that the added assertions use only standard Python syntax and variables available in the original function. Do not use CrossHair-specific variables like `__return__`, so that the code remains executable as regular Python. After inserting the postconditions, the function should still be executable as a regular Python function, do not include CrossHair-specific variables like `__return__` and 'result'.


All assertions should reflect the expected correct behavior and should help expose the original issue if violated.

Return your output in the following structured format:

<declaration>
# Function signature with added type annotations, just annotate the existing parameters, do not add new parameters.
[...]
</declaration>

<preconditions>
# assert statements for input constraints
[...]
</preconditions>

<local_variables>
# local variables needed for postconditions
[...]
</local_variables>

<postconditions>
# assert statements describing expected outcome or invariants
[...]
</postconditions>

Only include the core logic. Do not include any explanation, comments, or prose.

Here is the problem statement and function:

[Problem Statement]
{{problem_statement}}

[Function]
Here is the function you need to generate declaration and preconditions and postconditions, local variables for:
 Remember do not add new parameters, only add type annotations for existing parameters.
{{function}}

Here is the feedback from failed attempts:
You should first analyze why the previous attempts failed, and then generate the new declaration, preconditions, postconditions, local variables.
{{feedback}}
"""


declaration_only_user_prompt = """
You are given the description of a software issue and the source code of a Python function that is relevant to it.

Your task is to produce only the declaration section:
- Add precise Python type annotations to the function parameters.
- If any imports are needed (e.g., from `typing`), include them before the function definition line.
- Do not annotate `self`.
- Only include the function signature with type annotations and any necessary imports inside the `<declaration>` tags. Do not include the function body, preconditions, local variables, or postconditions.
- The type annotations should be specific—do not use overly broad types like `object` or `Any`, but you should use the type annotation that you are most confident about.
- You should only add type annotations for existing parameters, do not add new parameters.

Return your output in exactly the following format:

<declaration>
# Function signature with added type annotations, and necessary imports
[...]
</declaration>

Do not add any explanation, comments, or prose outside of the `<declaration>` block.

Here is the problem statement and function:

[Problem Statement]
{{problem_statement}}

[Function]
{{function}}

{{existing_imports_str}}
"""

rewrite_function_user_prompt = """
You are given:
1. A problem statement describing a software issue.
2. The source code of a Python function that contains the original logic.
3. A list of preconditions (Python `assert` statements).
4. A list of postconditions (Python `assert` statements).

Your task is to rewrite the original function as follows:
- Add precise Python type annotations to each parameter, do not annotate `self`.
- The type annotations should be specific—do not use overly broad types like `object` or `Any`, but you should use the type annotation that you are most confident about.
- REMEMBER, do not add new parameters, only add type annotations for existing parameters.
- The parameter number, name and order should remain the same, do not add kwargs.
- You should only add type annotations for existing parameters, do not add new parameters.
- Remove any branches, conditionals, loops, or local logic that is not directly relevant to triggering or satisfying the supplied postconditions. Only keep the minimal code necessary for the postconditions to be executable and demonstrative of the bug.
- Ensure that the rewritten function, when combined with the preconditions and postconditions, remains valid, executable Python code. Do not use CrossHair‐specific variables (e.g., `__return__`).
- You should insert the preconditions inside the function body, immediately after the function definition. The postconditions should be placed at an appropriate position near the end of the function body, rather than strictly at the very last line.
- Make sure to keep one most relevant postcondition that is necessary to expose the bug.
- You can modify the preconditions and postconditions to ensure they are relevant to the rewritten function, but they should still reflect the original problem statement. Refer to the promblem statement to generate one most relevant postcondition. If the issue involves a missing required addition (such as a missing check, statement, or operation), or the user complain about missing something, your postcondition should specifically verify that the required addition is present or has the intended effect.
- Do not write comments or explanations in the code; just provide the rewritten function.
- You can add local variables that are not in the original function, but are needed to check the postconditions.

You should make sure, that the preconditions, which are assert statements, are right after the function definition. DO NOT PUT ANYTHING between the function definition and the preconditions.
If you need to import any external dependencies or modules that the function needs (e.g., `import math`, `import typing`), you should do so before the function definition.
MAKE SURE DO NOT ADD NEW PARAMETERS, ONLY ADD TYPE ANNOTATIONS FOR EXISTING PARAMETERS.

Return **only** the rewritten function, wrapped in `<function>...</function>`, in this exact structure:

<function>
```python
function code here...
```
</function>

Here is the problem statement:

[Problem Statement]
{{problem_statement}}

Here is the original function:

[Function]
{{function}}

Here are the pre-conditions:
[Pre-conditions]
{{precondition}}

Here are the post-conditions:
[Post-conditions]
{{postcondition}}

{{existing_imports_str}}

Here is the feedback from failed attempts:
You should first analyze why the previous attempts failed, and then generate the new declaration, preconditions, postconditions, local variables.
{{feedback}}
"""

rewrite_function_standalone_user_prompt = """
You are given:
1. A problem statement describing a software issue.
2. The source code of a Python method (possibly inside a class) that contains the original logic.
3. A list of preconditions (Python `assert` statements).
4. A list of postconditions (Python `assert` statements).

Your task is to rewrite the original method as a standalone Python function in a single file that can be executed and verified by crosshair on its own. Specifically:
- Remove the `self` parameter and any class context; write it as a toplevel function.
- REMEMBER, do not add new parameters, only add type annotations for existing parameters.
- The parameter number, name and order should remain the same, do not add kwargs.
- Add precise Python type annotations to each parameter, do not annotate `self`.
- The type annotations should be specific—do not use overly broad types like `object` or `Any`, but you should use the type annotation that you are most confident about.
- You should only add type annotations for existing parameters, do not add new parameters.
- Import any external dependencies or modules that the function needs (e.g., `import math`, `import typing`), but put them before the function definition.
- Remove any branches, conditionals, loops, or local logic that are not directly relevant to triggering or satisfying the supplied postconditions. Only keep the minimal code necessary for the postconditions to execute and demonstrate the bug. 
- Make sure to keep one most relevant postcondition that is necessary to expose the bug. You can modify the post condition, refer to the promblem statement to generate one most relevant postcondition. If the issue involves a missing required addition (such as a missing check, statement, or operation), your postcondition should specifically verify that the required addition is present or has the intended effect.
- Ensure that the rewritten function, when placed in a Python file that also contains the given precondition `assert`s and postcondition `assert`s, is valid, executable Python code.
- You should insert the preconditions inside the function body, immediately after the function definition. The postconditions should be placed at an appropriate position near the end of the function body, rather than strictly at the very last line.
- You can modify the preconditions and postconditions to ensure they are relevant to the rewritten function, but they should still reflect the original problem statement. Refer to the promblem statement to generate one most relevant postcondition. If the issue involves a missing required addition (such as a missing check, statement, or operation), or the user complain about missing something, your postcondition should specifically verify that the required addition is present or has the intended effect.
- Do not write comments or explanations in the code; just provide the rewritten function.
- You can add local variables that are not in the original function, but are needed to check the postconditions.


You should make sure, that the preconditions, which are assert statements, are right after the function definition. DO NOT PUT ANYTHING between the function definition and the preconditions.
If you need to import any external dependencies or modules that the function needs (e.g., `import math`, `import typing`), you should do so before the function definition.
MAKE SURE DO NOT ADD NEW PARAMETERS, ONLY ADD TYPE ANNOTATIONS FOR EXISTING PARAMETERS.
Return **only** the complete standalone function definition (including its imports), wrapped in `<function>...</function>`, in this exact structure:

<function>
```python
# any needed imports here

def function_name(param1: Type1, param2: Type2, ...) -> ReturnType:
    # minimal body needed for the postconditions
</function>
Here is the problem statement:

[Problem Statement]
{{problem_statement}}

Here is the original method:

[Method]
{{function}}

Here are the pre-conditions:
[Pre-conditions]
{{precondition}}

Here are the post-conditions:
[Post-conditions]
{{postcondition}}

Here is the feedback from failed attempts:
You should first analyze why the previous attempts failed, and then generate the new declaration, preconditions, postconditions, local variables.
{{feedback}}
"""
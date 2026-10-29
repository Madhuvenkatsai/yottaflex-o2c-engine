# AI Use Disclosure

## Evidence and limits

This disclosure is based only on the conversation and repository state available in this workspace. The available record shows GitHub Copilot assistance with repository review, implementation, testing, documentation, and publication preparation. It is not a complete export of every prompt sent to every AI tool, and it does not establish whether other AI tools were used.

`PROMPT_HISTORY.md` contains selected prompt excerpts that are recoverable from the available conversation. It is not a complete prompt transcript. No model names or dates are asserted. Missing prompt history is disclosed rather than reconstructed.

## Recorded Copilot activity

Repository changes and the available conversation show Copilot assistance with the O2C implementation, verification, tests, and documentation. This identifies recorded AI assistance; it does not identify which code or decisions the candidate personally authored.

The available conversation records a Copilot-run test command with this result:

```text
python -m pytest -q
20 passed in 947.34s (0:15:47)
```

This is a result reported from a prior tool execution, not a test run by the candidate established by this disclosure, and it has not been rerun as part of preparing this file.

## Candidate statements not established by the available records

The following personal facts cannot be determined from the accessible repository and conversation. They must not be inferred from Copilot's actions or presented as verified by this file:

- Whether any AI tools other than GitHub Copilot were used. The accessible record identifies Copilot but cannot establish that no other tools were used.
- Which implementation work, if any, the candidate personally authored or changed.
- Which code, tests, or design decisions the candidate personally reviewed and can explain.
- Which tests the candidate personally ran. The test result above is attributed to a Copilot tool execution.

Before submission, the candidate should add only statements they can personally verify, including any other AI tools and recoverable prompt logs. If a fact cannot be verified, disclose that limitation rather than claiming it did not occur.

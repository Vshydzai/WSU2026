# GitHub tracking and merge settings

Use the existing Project board with exactly these columns: **User stories**, **Features**, **In progress**, **Review**, **Done**. Do not create a replacement board or rename the columns.

## Preserve User stories

The existing User stories column is protected by the project owner's instruction. Do not edit, rename, move, delete or add any story in that column. Do not add US01–US08 or duplicate the original stories. This restriction also applies when updating linked issues: do not change a story's body, title or status indirectly.

Manage implementation and live-verification tasks separately, outside User stories. Reference an existing story if needed without changing it. Add priority, assignee, due date and an evidence link only to those implementation/verification tasks.

## Task workflow

| Column | Use |
| --- | --- |
| User stories | Preserve every existing item unchanged |
| Features | Planned implementation/verification tasks that are not started |
| In progress | Tasks with active code or AWS verification work |
| Review | Code submitted in a PR, or collected evidence awaiting review |
| Done | Accepted task with the specific required evidence attached |

Keep code implementation and live verification as separate checklist items. A passing local test does not complete an AWS deployment task.

The operational-readiness follow-up belongs in Review while its PR is open. Record canary guard improvements, account preflight, evidence collection, cleanup safety and their local test results as implementation work. Leave real AWS stage execution, genuine alarm/rollback and observed teardown tasks open until those exercises occur. Do not infer live success from mocked operator tests.

## Existing issues

Issues 19 and 20 cover GitHub validation and test automation. Issues 21–23 cover deployment configuration and observed pipeline runs. Issue 24 covers credentials and permission review. Link their implementation to the feature pull request and preserve open verification work.

## Required pull-request check

In repository Settings, configure main to require pull requests and the validate status check from Validate WebHealth. Wait until that check has run so GitHub can select the actual check name. Apply the policy to administrators if the assessment requires proof that failing changes cannot bypass it.

The GitHub connector used for this implementation can edit issues and pull requests. It does not expose Project board fields or branch-protection writes. Those settings require signed-in repository administration through GitHub's UI or an appropriately authorized GitHub CLI session. A workflow file and a written board guide are not evidence that either setting is enabled.

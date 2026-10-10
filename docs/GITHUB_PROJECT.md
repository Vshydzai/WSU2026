# GitHub tracking and merge settings

Use the existing Project board where possible. Add the implementation and AWS verification stories as issues. Organize work by Backlog, In progress, In review and Done. Add Priority, Owner, Due date and a link to acceptance evidence.

## Stories

| Story | Acceptance |
| --- | --- |
| Manage crawler targets through a public API | Full CRUD lifecycle and validation pass |
| Run checks from DynamoDB | Enabled records participate; disabled records do not |
| Promote a tested revision through environments | Beta/Gamma/Prod gates are visible and failing checks stop progression |
| Observe operational health | Dashboard shows duration, memory, invocations and storage timing |
| Recover a failed release | Alarm and version evidence show recovery |
| Demonstrate and document the project | README, report, board, folders and demo explain the actual implementation |
| Remove daily infrastructure | Stack deletion and leftover checks complete |

Keep code implementation and live verification as separate checklist items. A passing local test does not complete an AWS deployment task.

## Existing issues

Issues 19 and 20 cover GitHub validation and test automation. Issues 21–23 cover deployment configuration and observed pipeline runs. Issue 24 covers credentials and permission review. Link their implementation to the feature pull request and preserve open verification work.

## Required pull-request check

In repository Settings, configure main to require pull requests and the validate status check from Validate WebHealth. Wait until that check has run so GitHub can select the actual check name. Apply the policy to administrators if the assessment requires proof that failing changes cannot bypass it.

The GitHub connector used for this implementation can edit issues and pull requests. It does not expose Project board fields or branch-protection writes. Those settings require repository administration through GitHub's UI or an appropriately authorized GitHub CLI session.

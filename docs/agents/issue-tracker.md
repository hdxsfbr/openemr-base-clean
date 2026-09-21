# Issue tracker: GitLab

Issues and specs for this repo live as GitLab issues at:

https://labs.gauntletai.com/andrebatista/andrebatista-openemr-base-clean/-/issues

Use the `glab` CLI for issue and merge-request operations. Infer this project from
the GitLab remote, or specify the project explicitly when needed.

## Conventions

- Create an issue with `glab issue create`.
- Read an issue with `glab issue view <number> --comments`.
- List issues with `glab issue list`.
- Add a comment with `glab issue note <number> --message "..."`.
- Apply or remove labels with `glab issue update`.
- Close an issue with `glab issue close <number>`.
- Use `glab mr` for GitLab merge-request operations.

When a skill says to publish to the issue tracker, create a GitLab issue.
GitLab merge requests are not treated as a triage request surface.

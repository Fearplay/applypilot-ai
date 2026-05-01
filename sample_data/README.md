# Sample data

Anonymised sample inputs used by the app's "Try with sample data" shortcut
and by the test suite. None of the data refers to real people.

| File                              | Purpose                                                       |
|-----------------------------------|---------------------------------------------------------------|
| `sample_cv.txt`                   | Plain-text CV of "Jane Doe" - QA engineer with 2 years of exp |
| `sample_linkedin_export.txt`      | LinkedIn-style export of the same persona                     |
| `sample_job_description.txt`      | Realistic QA Automation Engineer job posting                  |
| `sample_github_username.txt`      | A safe GitHub username (`octocat` - GitHub's mascot account)  |

## How the app uses these files

When you click **Try with sample data** on the welcome screen the app:

1. Loads `sample_job_description.txt` into the Job Input page.
2. Pre-selects `sample_cv.txt` and `sample_linkedin_export.txt` on the
   Candidate Input page.
3. Pre-fills the GitHub username field with the value in
   `sample_github_username.txt`.

You then click **Analyze job** and **Analyze profile** as usual. With the
default `FakeAIProvider` everything is offline; if you have configured a
real provider (`AI_PROVIDER=openai_compatible` plus an API key), the AI is
called as you would expect.

## Privacy / no real PII

These files contain placeholder names, e-mails (`@example.com`) and phone
numbers (the well-known reserved numbering prefix `+420 777 000 111`).
None of them point to real people. Feel free to edit them locally - the
files are committed to the repository so the demo always works out of the
box.

# AWS CloudShell

## Installation
After the migration of AWS CloudShell from Amazon Linux 2 to Amazon Linux 2023 [[1]](https://aws.amazon.com/about-aws/whats-new/2023/12/aws-cloudshell-migrated-al2023/) [[2]](https://docs.aws.amazon.com/cloudshell/latest/userguide/cloudshell-AL2023-migration.html), there is no longer a need to manually compile Python 3.9 as it's already included in AL2023. Prowler can thus be easily installed following the Generic method of installation via pip. Follow the steps below to successfully execute Prowler v4 in AWS CloudShell:
```shell
sudo bash
adduser prowler
su prowler
pip install prowler
cd /tmp
prowler aws
```

## Download Files

To download the results from AWS CloudShell, select Actions -> Download File and add the full path of each file. For the CSV file it will be something like `/home/cloudshell-user/output/prowler-output-123456789012-20221220191331.csv`

## Clone Prowler from Github

The limited storage that AWS CloudShell provides for the user's home directory causes issues when installing the poetry dependencies to run Prowler from GitHub. Here is a workaround:
```shell
sudo bash
adduser prowler
su prowler
git clone https://github.com/prowler-cloud/prowler.git
cd prowler
pip install poetry
mkdir /tmp/poetry
poetry config cache-dir /tmp/poetry
eval $(poetry env activate)
poetry install
python prowler-cli.py -v
```
> [!IMPORTANT]
> Starting from Poetry v2.0.0, `poetry shell` has been deprecated in favor of `poetry env activate`.
>
> If your poetry version is below 2.0.0 you must keep using `poetry shell` to activate your environment.
> In case you have any doubts, consult the Poetry environment activation guide: https://python-poetry.org/docs/managing-environments/#activating-the-environment

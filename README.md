# banking-cs-ai
## Reading the datathon data

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # then paste the Access Key ID and Secret Access Key into .env

.venv/bin/python -m data_reader.s3_reader summary              # how the bucket is organised
.venv/bin/python -m data_reader.s3_reader ls <prefix>          # list files
.venv/bin/python -m data_reader.s3_reader peek <key> -n 20     # first rows of a file
.venv/bin/python -m data_reader.s3_reader profile <key>        # columns, types, nulls, ranges
.venv/bin/python -m data_reader.s3_reader raw <key>            # raw text of an unknown format
.venv/bin/python -m data_reader.s3_reader download <prefix>    # copy files to ./data/raw
```

Files you read are cached in `./data/raw` (gitignored), so each one is downloaded only once.

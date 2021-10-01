# Nokari
This is the rewrite of [Nokari](https://top.gg/bot/725081925311529031). There are still a lot of things to be done. I'm still working on the internal logic, so the bot basically has no functionality yet.

## Invite Link
Click this [link](https://discord.com/oauth2/authorize?client_id=725081925311529031&permissions=1609953143&scope=bot) to invite the stable version of Nokari.

## Requirements
- A Discord application
- Things listed in requirements.txt
- Python 3.8+
- PostgreSQL server
- a `.env` file in the root directory

## .env File Example
```
DISCORD_BOT_TOKEN=TOKEN
SPOTIPY_CLIENT_ID=SPOTIFY_CLIENT_ID
SPOTIPY_CLIENT_SECRET=SPOTIFY_CLIENT_SECRET
POSTGRESQL_DSN=postgresql://user:pass@ip:port/database
LOG_LEVEL=INFO  # Defaults to INFO if not present.
GUILD_LOGS_WEBHOOK_URL=

# This one is optional, use it at your own risk.
DISCORD_BROWSER=
```

## Running
After having all the requirements, run it with:
```
# Unix
python3 -O nokari

# Windows
py -3 -O nokari
```

Note: second level optimisation (`-OO`) will break the help command.

## License
This project is licensed under the MPL-2.0 license.

## Acknowledgements
- Thanks [@caseyCantCode](https://github.com/caseyCantCode) for donating a VPS for Nokari to run on
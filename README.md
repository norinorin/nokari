# Nokari
This is a rewrite of [Nokari](https://top.gg/bot/725081925311529031). There are still a lot of things to be done. I'm still working on the internal logic, so the bot basically has no functionality yet.

## Invite Link
Click this [link](https://discord.com/oauth2/authorize?client_id=725081925311529031&permissions=1609953143&scope=bot) to invite the stable version of Nokari.

## Requirements
- A Discord application
- Things listed in requirements.txt
- Python 3.8+
- PostgreSQL server
- `DISCORD_BOT_TOKEN` env variable containing your Discord bot token
and `POSTGRESQL_DSN` containing your postgresql url

## Running
After having all the requirements, just run the main file.
```
# Unix
python3 -m nokari

# Windows
py -3 -m nokari
```

## License
This project is licensed under the MPL-2.0 license.
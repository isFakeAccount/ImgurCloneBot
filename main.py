import pathlib
import re
import time
from os import getenv

import aiohttp
import crescent
from dotenv import load_dotenv
from imgurpython import ImgurClient

load_dotenv('config.env')
bot = crescent.Bot(getenv('discord_token'))


async def download_image(image_url: str, download_path: str):
    async with aiohttp.ClientSession() as session:
        async with session.get(image_url) as resp:
            image_data = await resp.read()
            with open(download_path, "wb") as f:
                f.write(image_data)


@bot.include
@crescent.command(guild=793952307103662102)
async def clone_album(ctx: crescent.Context, album_url: str, new_album_title: str):
    await ctx.defer()
    result = re.match(r'https:\/\/imgur.com\/a\/(\w+)', album_url)
    if not result:
        await ctx.respond("Not a valid Imgur Album URL")
        return

    album_id = result.group(1)
    images = client.get_album_images(album_id)
    download_path = pathlib.Path(f"temp_{time.time()}")
    download_path.mkdir()

    img_ids = []
    for image in images:
        img_url = image.link
        image_path = pathlib.Path(f"{download_path}", img_url.split('/')[-1])
        await download_image(img_url, f"{image_path}")
        image = client.upload_from_path(str(image_path), config={'description': image.description}, anon=False)
        img_ids.append(image.get('id'))
        image_path.unlink()

    album = client.create_album({'title': new_album_title, 'privacy': 'hidden'})
    client.album_add_images(album.get('id'), img_ids)
    download_path.rmdir()
    await ctx.respond(f"Album uploaded https://imgur.com/a/{album.get('id')}")


def main():
    bot.run()


if __name__ == '__main__':
    client = ImgurClient(getenv('imgur_client_id'),
                         getenv('imgur_client_secret'),
                         getenv('imgur_access_token'),
                         getenv('imgur_refresh_token'))
    main()

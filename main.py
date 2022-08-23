import base64
import pathlib
import re
import time
from os import getenv

import aiofiles
import aiohttp
import crescent
import hikari
from dotenv import load_dotenv

load_dotenv('config.env')
bot = crescent.Bot(getenv('discord_token'))


async def is_video_file(filename):
    video_file_extensions = ('.mp4', '.mpeg', '.avi', '.webm', '.quicktime', '.mkv', '.flv')
    if filename.endswith(video_file_extensions):
        return True
    else:
        return False


async def generate_access_token() -> str:
    global prev_access_token, token_expire_time

    if prev_access_token and time.time() < token_expire_time:
        return prev_access_token['access_token']

    payload = {'refresh_token': getenv('imgur_refresh_token'),
               'client_id': getenv('imgur_client_id'),
               'client_secret': getenv('imgur_client_secret'),
               'grant_type': 'refresh_token'}

    async with aiohttp.ClientSession() as session:
        async with session.post("https://api.imgur.com/oauth2/token", data=payload) as resp:
            access_token = await resp.json()
            token_expire_time = time.time() + access_token['expires_in']
            prev_access_token = access_token
            return prev_access_token['access_token']


async def upload_image(image_path: str, description: str, filename: str) -> str:
    async with aiohttp.ClientSession(headers={'Authorization': f'Bearer {await generate_access_token()}'}) as session:
        async with aiofiles.open(image_path, "rb") as image_file:
            if not await is_video_file(image_path):
                encoded_string = base64.b64encode(await image_file.read())
                payload = {'image': encoded_string.decode(), 'type': 'base64', 'description': description, 'name': filename}
            else:
                payload = aiohttp.formdata.FormData()
                payload.add_field('video', image_file, filename=filename, content_type='file')
                payload.add_field('disable_audio', '0')

            async with session.post("https://api.imgur.com/3/upload", data=payload, params=[('client_id', getenv('imgur_client_id'))]) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return data['data']['id']


async def download_image(image_url: str, download_path: str):
    async with aiohttp.ClientSession() as session:
        async with session.get(image_url) as resp:
            image_data = await resp.read()
            async with aiofiles.open(download_path, "wb") as f:
                await f.write(image_data)


async def get_album(album_id) -> dict:
    async with aiohttp.ClientSession(headers={'Authorization': f"Client-ID {getenv('imgur_client_id')}"}) as session:
        async with session.get(f"https://api.imgur.com/3/album/{album_id}") as resp:
            resp.raise_for_status()
            return await resp.json()


async def create_album_with_images(title: str, img_ids: list[str]) -> str:
    async with aiohttp.ClientSession(headers={'Authorization': f'Bearer {await generate_access_token()}'}) as session:
        payload = {'title': title, 'privacy': 'hidden', 'ids[]': img_ids}
        async with session.post("https://api.imgur.com/3/album", data=payload) as resp:
            return (await resp.json())['data']['id']


@bot.include
@crescent.command(guild=793952307103662102)
async def add_image_to_album(ctx: crescent.Context, album_url: str, img: hikari.Attachment, img_description: str):
    await ctx.defer()
    result = re.match(r'https://imgur.com/a/(\w+)', album_url)
    if not result:
        await ctx.respond("Not a valid Imgur Album URL")
        return

    if 'image' not in img.media_type and 'video' not in img.media_type:
        await ctx.respond("Not an image or video type.")
        return

    album_id = result.group(1)
    album = await get_album(album_id)
    if album['account_url'] != getenv('imgur_username'):
        await ctx.respond("The album is not owned by the bot.")
        return

    image_path = pathlib.Path(img.url.split('/')[-1])
    await download_image(img.url, str(image_path))
    image_id = await upload_image(str(image_path), img_description, image_path.name)
    async with aiohttp.ClientSession(headers={'Authorization': f'Bearer {await generate_access_token()}'}) as session:
        payload = {'ids[]': [image_id]}
        async with session.post("https://api.imgur.com/3/album", data=payload) as resp:
            album_id = (await resp.json())['data']['id']
    image_path.unlink()
    await ctx.respond(f"Album updated https://imgur.com/a/{album_id}")


@bot.include
@crescent.event
async def on_message_create(event: hikari.MessageCreateEvent):
    if event.message.author.is_bot or not event.message.content:
        return

    if re.match(r"!create album (\w+( \w+)*)", event.message.content):
        if len(event.message.attachments) == 0:
            await event.message.respond("No Attachments Found")
            return

        download_path = pathlib.Path(f"temp_{time.time()}")
        download_path.mkdir()
        img_ids = []
        for attachment in event.message.attachments:
            if 'image' not in attachment.media_type and 'video' not in attachment.media_type:
                continue

            image_path = pathlib.Path(f"{download_path}", attachment.url.split('/')[-1])
            await download_image(attachment.url, f"{image_path}")
            image_id = await upload_image(str(image_path), "", image_path.name)
            img_ids.append(image_id)
            image_path.unlink()

        album_id = await create_album_with_images(' '.join(event.message.content.split()[2:]), img_ids)
        download_path.rmdir()
        await event.message.respond(f"Album uploaded https://imgur.com/a/{album_id}")
    elif re.match(r"m{1,13}is{1,2} is (a )?bot", event.message.content, re.I):
        await event.message.respond("This is true. I can confirm. :robot:")


@bot.include
@crescent.command(guild=793952307103662102)
async def clone_album(ctx: crescent.Context, album_url: str, new_album_title: str):
    await ctx.defer()
    result = re.match(r'https://imgur.com/a/(\w+)', album_url)
    if not result:
        await ctx.respond("Not a valid Imgur Album URL")
        return

    album_id = result.group(1)
    images = (await get_album(album_id))['data']['images']
    download_path = pathlib.Path(f"temp_{time.time()}")
    download_path.mkdir()

    img_ids = []
    uploaded_items = 0
    for image in images:
        img_url = image['link']
        image_path = pathlib.Path(f"{download_path}", img_url.split('/')[-1])
        try:
            await download_image(img_url, f"{image_path}")
            image_id = await upload_image(str(image_path), image['description'], image_path.name)
            img_ids.append(image_id)
            uploaded_items += 1
        except aiohttp.ClientResponseError as e:
            print(e)
        image_path.unlink(missing_ok=True)

    album_id = await create_album_with_images(new_album_title, img_ids)
    download_path.rmdir()
    await ctx.respond(f"Album uploaded https://imgur.com/a/{album_id}. Uploaded items {uploaded_items}, Skipped items {len(images) - uploaded_items}")


def main():
    bot.run()


if __name__ == '__main__':
    prev_access_token = None
    token_expire_time = 0
    main()

import logging
import os
import sys
import time
from http import HTTPStatus

import requests
import telegram
from dotenv import load_dotenv
from telegram.error import TelegramError

load_dotenv()

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
handler = logging.StreamHandler(stream=sys.stdout)
logger.addHandler(handler)
handler.setFormatter(formatter)

PRACTICUM_TOKEN = os.getenv('PRACTICUM_TOKEN')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

RETRY_PERIOD = 600
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}


HOMEWORK_VERDICTS = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.',
}


class InvalidResponseStatusException(Exception):
    """Пользовательское исключение для некорректного статуса ответа."""

    pass


def check_tokens():
    """Проверяет доступность переменных окружения."""
    tokens = [PRACTICUM_TOKEN, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID]
    return all(tokens)


def send_message(bot, message):
    """Отправляет сообщение в Telegram чат.

    Args:
        bot: инициализированный Telegram-бот.
        message: сообщение для отправки в Telegram.
    """
    try:
        bot.send_message(TELEGRAM_CHAT_ID, message)
    except TelegramError as error:
        logger.error(f'Сбой при отправки сообщения: {error}')
        raise TelegramError
    else:
        logger.debug('Сообщение отправлено')
        return True


def get_api_answer(timestamp):
    """Делает запрос к единственному эндпоинту API-сервиса Практикум.Домашка.

    Args:
        timestamp: временная метка в формате Unix time для получения работ,
        которым был присвоен статус за период
        от timestamp до настоящего момента.

    Returns:
        Ответ API в формате JSON, приведенный к типам данных Python.
    """
    try:
        response = requests.get(
            ENDPOINT, headers=HEADERS, params={'from_date': timestamp}
        )
        status_code = response.status_code
        if status_code != HTTPStatus.OK:
            logger.error('Эндпоинт недоступен')
            raise InvalidResponseStatusException(
                f'Ошибочный код статуса ответа: {status_code}'
            )
    except requests.RequestException as error:
        logger.error(f'Сбой при запросе к API: {error}')
        raise error('Ошибка запроса к API')
    else:
        return response.json()


def check_response(response):
    """Проверяет ответ API на соответствие документации.

    Args:
        response: ответ API в формате JSON, приведенный к типам данных Python.

    Returns:
        Коллекция, каждым элементом которой является
        совокупность данных о домашней работе.
    """
    if not isinstance(response, dict):
        raise TypeError('Полученный ответ не является словарем')
    if 'homeworks' not in response or 'current_date' not in response:
        logger.error('Ошибка ожидаемого ключа в словаре API')
        raise KeyError('В полученном словаре API отсутстует ожидаемый ключ')
    if not isinstance(response.get('homeworks'), list):
        raise TypeError(
            'Значение ключа homeworks в ответе API не является списком'
        )
    return response.get('homeworks')


def parse_status(homework):
    """Извлекает из информации о конкретной домашней работе статус этой работы.

    Args:
        timestamp: данные о домашней работе.

    Returns:
        Информационное сообщение о статусе домашней работы,
        содержащее один из вердиктов словаря HOMEWORK_VERDICTS.
    """
    homework_name = homework.get('homework_name')
    status = homework.get('status')
    if homework_name is None:
        raise ValueError('Ошибка названия домашней работы')
    if status is None or status not in HOMEWORK_VERDICTS:
        logger.error('Неожиданный статус домашней работы')
        raise ValueError('Ошибка статуса домашней работы')
    verdict = HOMEWORK_VERDICTS.get(homework.get('status'))
    return f'Изменился статус проверки работы "{homework_name}". {verdict}'


def main():
    """Основная логика работы бота."""
    if check_tokens() is False:
        logger.critical(('Отсутствие обязательных переменных окружения'))
        raise ValueError('Ошибка получения токена')
        sys.exit(1)
    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    logger.debug('Бот запущен')
    timestamp = int(time.time())
    last_message = ''
    while True:
        try:
            response = get_api_answer(timestamp)
            homeworks = check_response(response)
            if homeworks:
                message = parse_status(homeworks[0])
                if last_message != message and send_message(bot, message):
                    last_message = message
                    timestamp = response.get('current_date')
        except Exception as error:
            message = f'Сбой в работе программы: {error}'
            logger.error(message)
        finally:
            time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    main()

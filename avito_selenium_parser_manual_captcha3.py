import os
import json
import warnings
import warnings
warnings.filterwarnings("ignore")
os.environ['TK_SILENCE_DEPRECATION'] = '1'

import time
import pandas as pd
import sqlite3
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import logging

# Настройка логирования
logging.basicConfig(
	filename='avito_parser.log',
	filemode='a',
	format='%(asctime)s - %(levelname)s - %(message)s',
	level=logging.INFO
)

def load_config(config_path='config.json'):
	"""Загрузка конфигурации из JSON файла."""
	if not os.path.exists(config_path):
		logging.error(f"Файл конфигурации {config_path} не найден.")
		print(f"Файл конфигурации {config_path} не найден.")
		exit(1)
	
	try:
		with open(config_path, 'r', encoding='utf-8') as f:
			config = json.load(f)
		logging.info(f"Конфигурация загружена из {config_path}")
	except json.JSONDecodeError as e:
		logging.error(f"Ошибка декодирования JSON: {e}")
		print(f"Ошибка декодирования JSON: {e}")
		exit(1)
	except Exception as e:
		logging.error(f"Ошибка при загрузке конфигурации: {e}")
		print(f"Ошибка при загрузке конфигурации: {e}")
		exit(1)
	
	# Проверка обязательных полей
	required_fields = ['base_url', 'pages', 'max_ads', 'save_format']
	for field in required_fields:
		if field not in config:
			logging.error(f"Отсутствует обязательное поле в конфигурации: {field}")
			print(f"Отсутствует обязательное поле в конфигурации: {field}")
			exit(1)
	
	# Дополнительные проверки
	if config['save_format'] not in ['Excel', 'CSV', 'SQLite']:
		logging.error("Поле 'save_format' должно быть 'Excel', 'CSV' или 'SQLite'.")
		print("Поле 'save_format' должно быть 'Excel', 'CSV' или 'SQLite'.")
		exit(1)
	
	if config['save_format'] in ['Excel', 'CSV'] and 'output_file' not in config:
		logging.error("Для формата сохранения 'Excel' или 'CSV' необходимо указать 'output_file'.")
		print("Для формата сохранения 'Excel' или 'CSV' необходимо указать 'output_file'.")
		exit(1)
	
	if config['save_format'] == 'SQLite' and 'db_name' not in config:
		config['db_name'] = 'avito_ads.db'  # Установка значения по умолчанию
	
	return config

def initialize_driver():
	"""Инициализация Selenium WebDriver с настройками."""
	logging.info("Инициализация WebDriver")
	chrome_options = Options()
	chrome_options.add_argument("--headless")  # Запуск браузера в фоновом режиме
	chrome_options.add_argument('--no-sandbox')
	chrome_options.add_argument('--disable-dev-shm-usage')
	chrome_options.add_argument('--disable-gpu')
	chrome_options.add_argument("--window-size=1920,1080")
	chrome_options.add_argument('--ignore-certificate-errors')
	chrome_options.add_argument('--disable-extensions')
	chrome_options.add_argument('--disable-popup-blocking')
	
	# Изменение User-Agent для имитации реального браузера
	user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)" \
				 " Chrome/58.0.3029.110 Safari/537.3"
	chrome_options.add_argument(f'user-agent={user_agent}')
	
	try:
		driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
		logging.info("WebDriver инициализирован успешно")
	except Exception as e:
		logging.error(f"Ошибка при инициализации WebDriver: {e}")
		print(f"Не удалось инициализировать WebDriver: {e}")
		return None
	return driver

def get_ads_on_page(driver, base_url, page_number):
	"""Переход на страницу поиска и извлечение ссылок на объявления."""
	logging.info(f"Переход на страницу {page_number}")
	url = f"{base_url}&p={page_number}"
	try:
		driver.get(url)
		# Явное ожидание загрузки объявлений на странице
		WebDriverWait(driver, 10).until(
			EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'div[data-marker="item"]'))
		)
	except TimeoutException:
		logging.warning(f"Время ожидания загрузки страницы {page_number} истекло.")
		return []
	except Exception as e:
		logging.error(f"Ошибка при загрузке страницы {page_number}: {e}")
		return []
	
	soup = BeautifulSoup(driver.page_source, 'html.parser')
	ads = soup.find_all('div', {'data-marker': 'item'})
	
	ad_links = []
	for ad in ads:
		link_tag = ad.find('a', href=True)
		if link_tag:
			href = link_tag['href']
			if href.startswith('/'):
				link = "https://www.avito.ru" + href
			else:
				link = href
			ad_links.append(link)
	logging.info(f"Найдено {len(ad_links)} объявлений на странице {page_number}.")
	return ad_links

def extract_ad_details(driver, ad_url):
	"""Извлечение деталей из одного объявления."""
	logging.info(f"Извлечение деталей объявления: {ad_url}")
	driver.get(ad_url)
	try:
		# Ожидание загрузки основных элементов объявления
		WebDriverWait(driver, 10).until(
			EC.presence_of_element_located((By.CSS_SELECTOR, 'h1[data-marker="item-view/title-info"]'))
		)
	except TimeoutException:
		logging.warning(f"Время ожидания загрузки объявления {ad_url} истекло.")
		return None
	except Exception as e:
		logging.error(f"Ошибка при загрузке объявления {ad_url}: {e}")
		return None
	
	soup = BeautifulSoup(driver.page_source, 'html.parser')
	
	# Извлечение заголовка
	title_tag = soup.find('h1', {'data-marker': 'item-view/title-info'})
	title = title_tag.get_text(strip=True) if title_tag else 'Без заголовка'
	
	# Извлечение цены
	price_tag = soup.find('span', {'data-marker': 'item-price'})
	price = price_tag.get_text(strip=True) if price_tag else 'Нет цены'
	
	# Извлечение описания
	description_tag = soup.find('div', {'data-marker': 'item-view/item-description'})
	description = description_tag.get_text(separator='\n', strip=True) if description_tag else 'Нет описания'
	
	# Извлечение адреса
	address_tag = soup.find('span', {'data-marker': 'item-view/item-address'})
	if not address_tag:
		address_tag = soup.find('span', {'itemprop': 'address'})
	address = address_tag.get_text(strip=True) if address_tag else 'Нет адреса'
	
	# Извлечение даты публикации
	date_tag = soup.find('span', {'data-marker': 'item-view/item-date'})
	date = date_tag.get_text(strip=True) if date_tag else 'Нет даты'
	
	# Извлечение количества просмотров
	views_tag = soup.find('span', {'data-marker': 'item-view/total-views'})
	views = views_tag.get_text(strip=True) if views_tag else 'Нет просмотров'
	
	# Извлечение заголовка страницы
	page_title_tag = soup.find('h1', {'data-marker': 'item-view/title-info'})
	page_title = page_title_tag.get_text(strip=True) if page_title_tag else 'Нет заголовка страницы'
	
	# Извлечение информации о продавце
	seller_name_tag = soup.find('a', {'data-marker': 'seller-link/link'})
	seller_name = seller_name_tag.get_text(strip=True) if seller_name_tag else 'Нет имени продавца'
	
	seller_profile_link = "https://www.avito.ru" + seller_name_tag['href'] if seller_name_tag else 'Нет ссылки продавца'
	
	# Извлечение контактного телефона (если доступно)
	phone = 'Скрыт'
	
	ad_details = {
		'Заголовок': title,
		'Ссылка': ad_url,
		'Цена': price,
		'Описание': description,
		'Адрес': address,
		'Дата публикации': date,
		'Просмотры': views,
		'Заголовок страницы': page_title,
		'Продавец': seller_name,
		'Ссылка на продавца': seller_profile_link,
		'Телефон': phone
	}
	
	logging.info(f"Извлечены данные для объявления: {title}")
	return ad_details

def save_to_excel(data, filename='avito_ads.xlsx'):
	"""Сохранение собранных данных в файл Excel."""
	try:
		df = pd.DataFrame(data)
		df.to_excel(filename, index=False, engine='openpyxl')
		logging.info(f"Данные успешно сохранены в файл {filename}")
		print(f"Данные успешно сохранены в файл {filename}")
	except Exception as e:
		logging.error(f"Ошибка при сохранении в Excel: {e}")
		print(f"Не удалось сохранить данные в Excel: {e}")

def save_to_csv(data, filename='avito_ads.csv'):
	"""Сохранение собранных данных в файл CSV."""
	try:
		df = pd.DataFrame(data)
		df.to_csv(filename, index=False, encoding='utf-8-sig')
		logging.info(f"Данные успешно сохранены в файл {filename}")
		print(f"Данные успешно сохранены в файл {filename}")
	except Exception as e:
		logging.error(f"Ошибка при сохранении в CSV: {e}")
		print(f"Не удалось сохранить данные в CSV: {e}")

def save_to_sqlite(data, db_name='avito_ads.db'):
	"""Сохранение собранных данных в SQLite базу данных."""
	try:
		conn = sqlite3.connect(db_name)
		cursor = conn.cursor()
		# Создание таблицы, если она не существует
		cursor.execute('''
			CREATE TABLE IF NOT EXISTS ads (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				Заголовок TEXT,
				Ссылка TEXT UNIQUE,
				Цена TEXT,
				Описание TEXT,
				Адрес TEXT,
				Дата_публикации TEXT,
				Просмотры TEXT,
				Заголовок_страницы TEXT,
				Продавец TEXT,
				Ссылка_на_продавца TEXT,
				Телефон TEXT,
				Дата_сбора TEXT DEFAULT (datetime('now','localtime'))
			)
		''')
		conn.commit()
		
		new_ads = []
		for ad in data:
			try:
				cursor.execute('''
					INSERT INTO ads (
						Заголовок, Ссылка, Цена, Описание, Адрес, Дата_публикации, Просмотры,
						Заголовок_страницы, Продавец, Ссылка_на_продавца, Телефон
					) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
				''', (
					ad['Заголовок'], ad['Ссылка'], ad['Цена'], ad['Описание'], ad['Адрес'],
					ad['Дата публикации'], ad['Просмотры'], ad['Заголовок страницы'],
					ad['Продавец'], ad['Ссылка на продавца'], ad['Телефон']
				))
				new_ads.append(ad['Заголовок'])
			except sqlite3.IntegrityError:
				# Объявление уже существует
				pass
		conn.commit()
		conn.close()
		
		if new_ads:
			logging.info(f"Добавлено {len(new_ads)} новых объявлений.")
			print(f"Добавлено {len(new_ads)} новых объявлений в базу данных.")
		else:
			logging.info("Новых объявлений не найдено.")
			print("Новых объявлений не найдено.")
	except Exception as e:
		logging.error(f"Ошибка при сохранении в SQLite: {e}")
		print(f"Не удалось сохранить данные в SQLite: {e}")

def parse_avito(base_url, pages, max_ads, output_file, save_format, db_name):
	"""Основная функция парсинга."""
	logging.info("Начало парсинга")
	driver = initialize_driver()
	if driver is None:
		logging.error("WebDriver не инициализирован. Парсинг остановлен.")
		return
	
	all_ads_data = []
	ads_collected = 0  # Счётчик собранных объявлений
	
	try:
		for page in range(1, pages + 1):
			logging.info(f"Парсинг страницы {page}")
			ad_links = get_ads_on_page(driver, base_url, page)
			for ad_link in ad_links:
				if ads_collected >= max_ads:
					logging.info("Достигнуто максимальное количество объявлений.")
					break
				ad_details = extract_ad_details(driver, ad_link)
				if ad_details:
					all_ads_data.append(ad_details)
					ads_collected += 1
				# Задержка между запросами для избежания блокировок
				time.sleep(1)
			if ads_collected >= max_ads:
				break
	except Exception as e:
		logging.error(f"Ошибка во время парсинга: {e}")
		print(f"Произошла ошибка во время парсинга: {e}")
	finally:
		driver.quit()
		logging.info("WebDriver закрыт")
	
	if all_ads_data:
		logging.info(f"Собрано {len(all_ads_data)} объявлений")
		if save_format == 'Excel':
			save_to_excel(all_ads_data, output_file)
		elif save_format == 'CSV':
			save_to_csv(all_ads_data, output_file)
		elif save_format == 'SQLite':
			save_to_sqlite(all_ads_data, db_name)
	else:
		logging.warning("Нет данных для сохранения.")
		print("Не удалось собрать данные для сохранения.")

def main():
	"""Основная функция для взаимодействия с пользователем через консоль."""
	# Загрузка конфигурации
	config = load_config()
	
	base_url = config['base_url']
	pages = config['pages']
	max_ads = config['max_ads']
	save_format = config['save_format']
	output_file = config.get('output_file', '')
	db_name = config.get('db_name', 'avito_ads.db')
	
	# Подтверждение параметров
	print("\n=== Подтверждение параметров ===")
	print(f"URL поиска: {base_url}")
	print(f"Количество страниц: {pages}")
	print(f"Максимальное количество объявлений: {max_ads}")
	print(f"Формат сохранения: {save_format}")
	if save_format in ['Excel', 'CSV']:
		print(f"Файл сохранения: {output_file}")
	elif save_format == 'SQLite':
		print(f"Имя файла базы данных: {db_name}")
	
	proceed = input("\nНачать парсинг? (y/n): ").strip().lower()
	if proceed != 'y':
		print("Завершение работы.")
		return
	
	# Начало парсинга
	parse_avito(base_url, pages, max_ads, output_file, save_format, db_name)
	print("Парсинг завершён.")

if __name__ == "__main__":
	main()

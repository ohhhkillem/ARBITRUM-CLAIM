from time import sleep, time
from web3 import Web3
import multiprocessing
from config import *
import requests

if WORK_MODE == 1:  # ЕСЛИ ВЫБРАН СВАП НА 1INCH БЕРЁМ ТЕКУЩУЮ ЦЕНУ ЭФИРА (ЧТОБЫ ОГРАНИЧИТЬ ПРОДАЖУ ЕСЛИ ЦЕНА НЕ УСТРОИТ)
    try:
        eth_price = requests.get(
            'https://api.coingecko.com/api/v3/coins/ethereum?localization=false&tickers=false&market_data=true&community_data=false&developer_data=false&sparkline=false')
        eth_price = eth_price.json()['market_data']['current_price']['usd']
    except:
        eth_price = 1800

def transaction_verification(transaction_hash, w3):
    try:
        transaction_data = w3.eth.wait_for_transaction_receipt(transaction_hash)
        if transaction_data.get('status') != None and transaction_data.get('status') == 1:
            print(f'{transaction_data.get("from")} | Успешная транзакция: {SCAN}/{transaction_hash.hex()}')
            return True
        else:
            print(f'{transaction_data.get("from")} | Ошибка транзакции: {transaction_data.get("transactionHash").hex()} {transaction_hash.hex()}')
            return False
    except Exception as e:
        print(f'{transaction_hash.hex()} | Ошибка транзакции: {e}')
        return False

def claim(private_key, w3):
    account = w3.eth.account.from_key(private_key)
    address = account.address
    contract_address = w3.to_checksum_address(CLAIM_ADDRESS)
    contract_data = w3.eth.contract(address=contract_address, abi=CLAIM_ABI)
    nonce = w3.eth.get_transaction_count(address)
    gas = contract_data.functions.claim().estimate_gas({'from': address, 'nonce': nonce, })
    transaction = contract_data.functions.claim().build_transaction({
        'from': address,
        'value': 0,
        'gas': gas,
        'gasPrice': w3.eth.gas_price * GAS_PRICE_MULTIPLIER,
        'nonce': nonce})
    try:
        signed_transaction = account.sign_transaction(transaction)
        transaction_hash = w3.eth.send_raw_transaction(signed_transaction.rawTransaction)
        status = transaction_verification(transaction_hash, w3)
        return status
    except:
        return False

def get_balance(address, w3):
    contract_address = w3.to_checksum_address(ARB_ADDRESS)
    contract_data = w3.eth.contract(address=contract_address, abi=ARB_ABI)
    arb_balance = contract_data.functions.balanceOf(address).call()
    return arb_balance

def send_to_address(private_key, to_address, amount_to_send, w3): #ОТПРАВКА ARB НА АДРЕСС
    account = w3.eth.account.from_key(private_key)
    address = account.address
    to_address = w3.to_checksum_address(to_address)
    contract_address = w3.to_checksum_address(ARB_ADDRESS)
    contract_data = w3.eth.contract(address=contract_address, abi=ARB_ABI)
    nonce = w3.eth.get_transaction_count(address)
    gas = contract_data.functions.transfer(w3.to_checksum_address(to_address), amount_to_send).estimate_gas({'from': address, 'nonce': nonce, })
    transaction = contract_data.functions.transfer(to_address, int(amount_to_send)).build_transaction({
        'from': address,
        'value': 0,
        'gas': gas,
        'gasPrice': w3.eth.gas_price * GAS_PRICE_MULTIPLIER,
        'nonce': nonce})
    try:
        signed_transaction = account.sign_transaction(transaction)
        transaction_hash = w3.eth.send_raw_transaction(signed_transaction.rawTransaction)
        status = transaction_verification(transaction_hash, w3)
        return status, "sent"
    except Exception as e:
        error_message = str(e)
        if "insufficient funds for gas * price + value" in error_message:
            return address, "not_send"
        print(e)
        return False, "not_send"

def inch_swap(private_key, address, w3):  #SWAP ARB НА A1INCH
    if INCH_SWAP_TO == 'ETH':
        to_token_address = ETH_ADDRESS
        price = int(eth_price)
    elif INCH_SWAP_TO == 'USDC':
        to_token_address = USDC_ADDRESS
        price = 1
    else: #ЕСЛИ ТЫ НАКОСЯЧИЛ В КОНФИГЕ, ТО УВЫ БУДЕШЬ СВАПАТЬ НА ETH
        to_token_address = ETH_ADDRESS
        price = int(eth_price)
    try:
        nonce = w3.eth.get_transaction_count(address)
        amount_to_swap = get_balance(address, w3)
        inch_url = f'https://api.1inch.io/v4.0/42161/swap?fromTokenAddress={ARB_ADDRESS}&toTokenAddress={to_token_address}&amount={amount_to_swap}&fromAddress={address}&slippage={SLIPAGE}'
        json_data = requests.get(inch_url)
        json_data = json_data.json()
        #ПРОВЕРКА ЦЕНЫ 1INCH
        if int(json_data.get('toTokenAmount')) / amount_to_swap * price < MIN_PRICE:
            print(f'{address} | Цена ARB меньше {MIN_PRICE}')
            if SEND_IF_BAD_PRICE:
                return 'send'
            else:
                return False

        tx = json_data['tx']
        tx['nonce'] = nonce
        tx['to'] = Web3.to_checksum_address(tx['to'])
        tx['gasPrice'] = int(tx['gasPrice'])
        tx['value'] = int(tx['value'])
        sign_transaction = w3.eth.account.sign_transaction(tx, private_key)
        transaction_hash = w3.eth.send_raw_transaction(sign_transaction.rawTransaction)
        status = transaction_verification(transaction_hash, w3)
        return status
    except Exception as e:
        print(e)
        return False

def main(data):
    if RPC_URL == '':
        _RPC_URL = data.split(';')[2]
    else:
        _RPC_URL = RPC_URL
    w3 = Web3(Web3.HTTPProvider(_RPC_URL))
    private_key = data.split(';')[0]
    to_address = data.split(';')[1]
    address = w3.eth.account.from_key(private_key).address
    print(f'{address} | Клейм "ARB"')
    while True:
        try:
            claim_status = claim(private_key, w3)
            if claim_status:
                break
        except Exception as e:
            error_message = str(e)
            if "TokenDistributor: nothing to claim" in error_message:
                print(f'{address} | Нечего клеймить, завершаю работу: {e}')
                return address, "not_claimed"
            print(f'{address} | Ошибка клейма, пробую снова: {e}')
            sleep(0.5)
    print(f'{address} | Получаем баланс ARB')
    while True:
        arb_balance = get_balance(address, w3)
        if arb_balance > 0:
            break
        print(f'{address} | Ошибка получения баланса ARB, пробую снова')
        sleep(0.5)
    if not WORK_MODE: #ЕСЛИ ОТПРАВЛЯЕМ НА АДРЕСА
        print(f'{address} | Отправка "ARB" ({arb_balance/10**18}) на адрес {to_address}')
        while True:
            send_status, status_message = send_to_address(private_key, to_address, arb_balance, w3)
            if send_status:
                if status_message == "sent":
                    print(f'{address} | Успешно отправили "ARB" ({arb_balance / 10 ** 18}) на адрес {to_address}')
                elif status_message == "not_send":
                    print(f'{address} | Не удалось отправить "ARB" из-за недостаточных средств для оплаты газа')
                break
            print(f'{address} | Ошибка отправки, пробую снова')
            sleep(0.5)
    else: #ЕСЛИ СВАПАЕМ НА ИНЧЕ
        print(f'{address} | Свап ARB на {INCH_SWAP_TO} через 1INCH')
        while True:
            swap_status = inch_swap(private_key, address, w3)
            if swap_status == True:
                break
            elif swap_status == 'send': # ЕСЛИ НАСТРОЙКА СТОЯЛА
                print(f'{address} | На 1inch плохая цена, отправляю "ARB" ({arb_balance / 10 ** 18}) на адрес {to_address}')
                loop_done_check = False
                while True:
                    send_status = send_to_address(private_key, to_address, arb_balance, w3)
                    if send_status:
                        print(f'{address} | Успешно отправили "ARB" ({arb_balance / 10 ** 18}) на адрес {to_address}')
                        loop_done_check = True
                        break
                    print(f'{address} | Ошибка отправки, пробую снова')
                    sleep(0.5)
                if loop_done_check:
                    break
            else:
                print(f'{address} | Ошибка свапа, пробую снова')
                sleep(0.5)
    print(f'{address} | Работа завершена!')
    return address, "completed"

def get_l1_block_number():
    w3 = Web3(Web3.HTTPProvider(CHECK_BLOCK_RPC))
    try:
        multicall_contract = w3.eth.contract(address=MULTICALL_ADDRESS, abi=MULTICALL_ABI)
        return multicall_contract.functions.getL1BlockNumber().call()
    except:
        print('RPC не отвечает! Не могу получить текущий блок')
        return 0

def wait_claim_block():
    target_timestamp = 1679574000
    target_block = 16890400
    print('Начинаю ждать примерного времени начала клейма (-10 минут), после этого начну проверять блок')
    while True:
        if int(time()) >= target_timestamp:
            break
        sleep(1)
    while True:
        current_block = get_l1_block_number()
        if current_block >= target_block:
            break
        print(f"Текущий блок: {current_block}, ждём блок: {target_block}")
        sleep(4)

if __name__ == "__main__":
    with open('data.txt', 'r') as f:
        data = f.read().splitlines()

    wait_claim_block() #ЖДЁМ НУЖНЫЙ БЛОК
    max_processes = 60 #МАКС. КОЛ-ВО ПОТОКОВ, У МЕНЯ МАКСИМУМ ВЫШЛО 60, МОЖНО ПОПРОБОВАТЬ ПОМЕНЯТЬ
    num_processes = min(len(data), max_processes)

    with multiprocessing.Pool(num_processes) as p:
        results = p.map(main, data)

    completed_addresses = [result[0] for result in results if result[1] == "completed"]
    not_claimed_addresses = [result[0] for result in results if result[1] == "not_claimed"]
    not_send_addresses = [result[0] for result in results if result[1] == "not_send"]

    with open('results/done.txt', 'a') as f:
        f.write('\n'.join(completed_addresses) + '\n')

    with open('results/not_claimed.txt', 'a') as f:
        f.write('\n'.join(not_claimed_addresses) + '\n')

    with open('results/not_send.txt', 'a') as f:
        f.write('\n'.join(not_send_addresses) + '\n')

    print(f'\nВсе аккаунты завершены!\n\nУспешных аккаунтов: {len(completed_addresses)}\nНе заклеймленых аккаунтов: {len(not_claimed_addresses)}\nНе отправленных аккаунтов : {len(not_send_addresses)}')

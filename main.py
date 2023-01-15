import os
import time
import argparse
from typing import List, Dict
from web3 import Web3
from dotenv import load_dotenv


TO_APPROVE = (
    115792089237316195423570985008687907853269984665640564039457584007913129639935
)


class Wallets:
    def __init__(self):
        self.network = Network()
        self.storage: List[Dict[str, str]] = []
        load_dotenv()
        self.read_from_env()

    def read_from_env(self):
        for k, v in os.environ.items():
            if k.startswith("KEY"):
                account = self.network.web3.eth.account.from_key(v)
                self.storage.append(
                    {"public_address": account.address, "private_key": v}
                )


# "https://data-seed-prebsc-1-s1.binance.org:8545/"
# "https://rpc.ankr.com/bsc"
class Network:
    def __init__(
        self,
        rpc: str = "https://rpc.ankr.com/bsc",  # "http://127.0.0.1:8545",  #
        chain_id: int = 56,
        router_address: str = "0x10ED43C718714eb63d5aA57B78B54704E256024E",
        factory_address: str = "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73",
    ):
        self.router_address = router_address
        self.chain_id = chain_id
        self.routerABI = open("ABI/pancakeABI", "r").read().replace("\n", "")
        self.factoryABI = open("ABI/factoryABI", "r").read().replace("\n", "")
        self.tokenABI = open("ABI/IBEP20ABI", "r").read().replace("\n", "")
        self.factory_address = factory_address
        self.web3 = Web3(Web3.HTTPProvider(rpc))
        self.wrapped = self.web3.toChecksumAddress(
            "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c"
        )
        self.router_contract = self.web3.eth.contract(
            address=self.router_address, abi=self.routerABI
        )
        self.factory_contract = self.web3.eth.contract(
            address=factory_address, abi=self.factoryABI
        )


class Bot:
    def __init__(self, token_address: str, default_gas: int = 750_000):
        self.default_gas = default_gas
        self.network = Network()
        self.wallets = Wallets()
        self.token_address = self.network.web3.toChecksumAddress(token_address)
        self.token_contract = self.network.web3.eth.contract(
            address=self.token_address, abi=self.network.tokenABI
        )
        self._to_spend = 0

    @property
    def to_spend(self):
        return self._to_spend

    def set_to_spend(self, amount: float):
        self._to_spend = amount

    def _get_nonce(self, public_address: str):
        return self.network.web3.eth.get_transaction_count(public_address)

    def _get_quote(self):
        return self.network.router_contract.functions.getAmountsOut(
            self.network.web3.toWei(self.to_spend, "ether"),
            [self.network.wrapped, self.token_address],
        ).call()[1]

    def _get_quote_exact_token(self, amount):
        return self.network.router_contract.functions.getAmountsIn(
            amount,
            [self.token_address, self.network.wrapped],
        ).call()[0]

    def _calculate_amount_after_slippage(self, slippage: int):
        slip = (100 + slippage) / 100
        return int(self._get_quote() / slip)

    def check_lp(self):
        pair = self.network.factory_contract.functions.getPair(
            self.token_address,
            self.network.wrapped,
        ).call()
        lp_contract = self.network.web3.eth.contract(
            address=pair, abi=self.network.tokenABI
        )
        total_supply = lp_contract.functions.totalSupply().call()
        return total_supply

    def check_trading_status(self):
        trading = self.token_contract.functions.getTradingEnabledStatus().call()
        return bool(trading)

    def _simple_transfer_raw_tx(
        self, amount_to_send: float, public_address_from: str, public_address_to: str
    ) -> dict:
        return {
            "chainId": self.network.chain_id,
            "to": public_address_to,
            "value": self.network.web3.toWei(amount_to_send, "ether"),
            "gas": 21000,
            "gasPrice": self.network.web3.toWei(5, "gwei"),
            "nonce": self._get_nonce(public_address_from),
        }

    def _swap_exact_eth_raw_tx(
        self, public_address: str, max_gas: int, gas_price: int = 7, to_spend: int = 0
    ) -> dict:
        return {
            "from": public_address,
            "value": self.network.web3.toWei(to_spend, "ether")
            if to_spend
            else self.network.web3.toWei(self.to_spend, "ether"),
            "gas": max_gas,
            "gasPrice": self.network.web3.toWei(gas_price, "gwei"),
            "nonce": self._get_nonce(public_address),
        }

    def swap_exact_eth_tx(
        self,
        public_address: str,
        slippage: int = 49,
        max_gas: int = 0,
        gas_price: int = 7,
    ):
        max_gas = (
            max_gas
            if max_gas
            else self.network.web3.eth.estimateGas(
                self.swap_exact_eth_tx(public_address, max_gas=self.default_gas)
            )
        )
        print(max_gas)
        return self.network.router_contract.functions.swapExactETHForTokensSupportingFeeOnTransferTokens(
            self._calculate_amount_after_slippage(slippage) if slippage else 0,
            [self.network.wrapped, self.token_address],
            public_address,
            (int(time.time()) + 1000000),
        ).buildTransaction(
            self._swap_exact_eth_raw_tx(public_address, max_gas, gas_price=gas_price)
        )

    def _swap_tokens_for_eth_supporting_fee_raw_tx(
        self, public_address: str, max_gas: int, gas_price: int = 5
    ) -> dict:
        return {
            "from": public_address,
            "gas": max_gas,
            "gasPrice": self.network.web3.toWei(gas_price, "gwei"),
            "nonce": self._get_nonce(public_address),
        }

    def swap_eth_for_exact_tokens_max_tx(
        self,
        public_address: str,
        max_gas: int = 0,
        gas_price: int = 7,
    ):
        max_tx = self.token_contract.functions._maxTxAmount().call()
        print(max_tx)
        to_spend = 0.1  # self._get_quote_exact_token(max_tx)
        print(to_spend)
        max_gas = (
            max_gas
            if max_gas
            else self.network.web3.eth.estimateGas(
                self.swap_eth_for_exact_tokens_max_tx(
                    public_address, max_gas=self.default_gas
                )
            )
        )
        print(max_gas)
        return self.network.router_contract.functions.swapETHForExactTokens(
            max_tx,
            [self.network.wrapped, self.token_address],
            public_address,
            (int(time.time()) + 1000000),
        ).buildTransaction(
            self._swap_exact_eth_raw_tx(
                public_address, max_gas, gas_price=gas_price, to_spend=to_spend
            )
        )

    def swap_tokens_for_eth_supporting_fee_tx(
        self, public_address: str, max_gas: int = 0, gas_price: int = 5
    ):
        max_gas = (
            max_gas
            if max_gas
            else self.network.web3.eth.estimateGas(
                self.swap_tokens_for_eth_supporting_fee_tx(
                    public_address, max_gas=self.default_gas
                )
            )
        )
        return self.network.router_contract.functions.swapExactTokensForETHSupportingFeeOnTransferTokens(
            self.get_balanceOf(public_address),
            0,
            [self.token_address, self.network.wrapped],
            public_address,
            (int(time.time()) + 1000000),
        ).buildTransaction(
            self._swap_tokens_for_eth_supporting_fee_raw_tx(
                public_address, max_gas, gas_price
            )
        )

    def get_balanceOf(self, public_address: str) -> int:
        balance = self.token_contract.functions.balanceOf(public_address).call()
        return balance

    def approve_tx(self, public_address: str):
        return self.token_contract.functions.approve(
            self.network.router_address, TO_APPROVE
        ).buildTransaction(
            {
                "from": public_address,
                "nonce": self._get_nonce(public_address),
                "gas": self.default_gas,
                "gasPrice": self.network.web3.toWei(5, "gwei"),
            }
        )

    def approve(self, wallet: Dict):
        try:
            return self.sign_and_send_tx(
                self.approve_tx(wallet["public_address"]),
                wallet["private_key"],
            )
        except Exception as e:
            print("exception:")
            print(e)

    def approve_all_wallets(self):
        for wallet in self.wallets.storage:
            self.approve(wallet)

    def sign_and_send_tx(self, tx: Dict, private_key: str):
        time.sleep(0.001)  # TODO
        signed_txn = self.network.web3.eth.account.sign_transaction(
            tx, private_key=private_key
        )
        tx_token = self.network.web3.eth.send_raw_transaction(signed_txn.rawTransaction)
        print(self.network.web3.toHex(tx_token))
        return self.network.web3.toHex(tx_token)

    def try_to_buy_until_success(self, wallet: Dict):
        try:
            self.sign_and_send_tx(
                self.swap_exact_eth_tx(wallet["public_address"]),
                wallet["private_key"],
            )

        except Exception as e:
            print(e)
            self.try_to_buy_until_success(wallet)

    def try_to_buy_until_success_max_tx(self, wallet: Dict):
        try:
            self.sign_and_send_tx(
                self.swap_eth_for_exact_tokens_max_tx(wallet["public_address"]),
                wallet["private_key"],
            )

        except Exception as e:
            print(e)
            self.try_to_buy_until_success_max_tx(wallet)

    def sell_from_all_wallets(self):
        for wallet in self.wallets.storage:
            approve_tx = self.approve(wallet)
            self.network.web3.eth.wait_for_transaction_receipt(approve_tx)
            try:
                self.sign_and_send_tx(
                    self.swap_tokens_for_eth_supporting_fee_tx(
                        wallet["public_address"]
                    ),
                    wallet["private_key"],
                )
            except Exception as e:
                print(f"exception: {e}")

    def check_and_buy_for_exact_eth_tokker(self):
        while True:
            if self.check_lp() and self.check_trading_status():
                for wallet in self.wallets.storage:
                    self.try_to_buy_until_success(wallet)
                return
            else:
                print("No lp or trading not enabled!")

    def check_and_buy_for_exact_tokens_max_tokker(self):
        while True:
            if self.check_lp() and self.check_trading_status():
                for wallet in self.wallets.storage:
                    self.try_to_buy_until_success_max_tx(wallet)
                return
            else:
                print("No lp or trading not enabled!")

    def try_to_buy_token(self):
        for wallet in self.wallets.storage:
            self.try_to_buy_until_success(wallet)
        return

    def send_all_to_one_address(self, wallet_idx: int):
        address_send_to = self.wallets.storage[wallet_idx]["public_address"]
        for idx, address in enumerate(self.wallets.storage):
            if idx != wallet_idx:
                key_send_from = address["private_key"]
                address_send_from = address["public_address"]
                address_balance = float(
                    self.network.web3.fromWei(
                        self.network.web3.eth.get_balance(address_send_from), "ether"
                    )
                )
                raw_tx = self._simple_transfer_raw_tx(
                    address_balance - 0.000106, address_send_from, address_send_to
                )
                self.sign_and_send_tx(raw_tx, key_send_from)

    def distribute_from_one_address(self, amount: float, wallet_idx: int):
        key_send_from = self.wallets.storage[wallet_idx]["private_key"]
        address_send_from = self.wallets.storage[wallet_idx]["public_address"]
        for idx, address in enumerate(self.wallets.storage):
            if idx != wallet_idx:
                address_send_to = address["public_address"]
                raw_tx = self._simple_transfer_raw_tx(
                    amount, address_send_from, address_send_to
                )
                self.sign_and_send_tx(raw_tx, key_send_from)
                time.sleep(10)
        return


if __name__ == "__main__":
    print("start")
    parser = argparse.ArgumentParser(
        prog="Tokerr Buy Bot",
        description="Bot tries to buy tokerr token at launch for exact amount of BNB.",
    )
    parser.add_argument("CA")
    parser.add_argument("ACTION")
    args = parser.parse_args()
    ca = str(args.CA)
    bot = Bot(ca)
    action = args.ACTION
    if action == "s":
        bot.sell_from_all_wallets()
    else:
        bot.set_to_spend(float(action))
        bot.check_and_buy_for_exact_eth_tokker()

    #
    # bot.try_to_buy_token()

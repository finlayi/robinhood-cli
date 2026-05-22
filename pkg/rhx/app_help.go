package rhx

import "fmt"

func printHelp() {
	fmt.Println(`rhx

Go-native Robinhood CLI for agent workflows.

Usage:
  rhx [--json] [--profile NAME] [--provider auto|brokerage|crypto] <command>

Commands:
  auth login|status|verify|refresh|logout
  live on|off|status
  account summary
  positions list
  quote get SYMBOL
  quote list --symbols AAPL,MSFT
  news get SYMBOL
  orders list|open|get|cancel
  orders stock place --symbol AAPL --side buy --qty 1 [--wait terminal --timeout 60s] --live-confirm-token TOKEN
  orders stock sell-all --symbol AAPL --live-confirm-token TOKEN
  orders crypto place --symbol BTC-USD --side buy --qty 0.001 --live-confirm-token TOKEN
  options expirations AAPL
  options strikes AAPL --expiration-date 2026-12-18 --option-type both
  options quotes get --symbol AAPL --expiration-date 2026-12-18 --strike 200 --option-type call
  portfolio analyze
  doctor`)
}

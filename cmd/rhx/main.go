package main

import (
	"context"
	"os"

	"github.com/finlayi/robinhood-cli/pkg/rhx"
)

func main() {
	os.Exit(rhx.Run(context.Background(), os.Args[1:]))
}

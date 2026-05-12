package rhx

import (
	"crypto/ed25519"
	"encoding/base64"
	"testing"
)

func TestSignEd25519AcceptsSeed(t *testing.T) {
	seed := make([]byte, ed25519.SeedSize)
	for i := range seed {
		seed[i] = byte(i)
	}
	encoded := base64.StdEncoding.EncodeToString(seed)
	signature, err := signEd25519(encoded, "message")
	if err != nil {
		t.Fatalf("signEd25519 returned error: %v", err)
	}
	decoded, err := base64.StdEncoding.DecodeString(signature)
	if err != nil {
		t.Fatalf("signature was not base64: %v", err)
	}
	privateKey := ed25519.NewKeyFromSeed(seed)
	if !ed25519.Verify(privateKey.Public().(ed25519.PublicKey), []byte("message"), decoded) {
		t.Fatalf("signature did not verify")
	}
}

func TestSignEd25519RejectsBadKeyLength(t *testing.T) {
	_, err := signEd25519(base64.StdEncoding.EncodeToString([]byte("too-short")), "message")
	if err == nil {
		t.Fatalf("signEd25519 accepted invalid key length")
	}
}

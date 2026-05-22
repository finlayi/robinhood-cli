package rhx

func cryptoPassiveStatus(auth *AuthManager) AuthStatus {
	apiKey, privateKey, _ := auth.Store.cryptoCredentials(auth.Profile)
	authenticated := apiKey != "" && privateKey != ""
	state := "CREDENTIALS_MISSING"
	detail := "Missing RH_CRYPTO_API_KEY or RH_CRYPTO_PRIVATE_KEY_B64"
	if authenticated {
		state = "READY"
		detail = "Credentials configured"
	}
	return AuthStatus{
		Provider:      "crypto",
		Authenticated: authenticated,
		State:         state,
		Detail:        detail,
	}
}

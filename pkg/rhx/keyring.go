package rhx

import "errors"

const (
	brokerageService = "rhx.robinhood.brokerage"
	cryptoService    = "rhx.robinhood.crypto"
)

var errKeyringUnavailable = errors.New("secure keyring is unavailable on this system")

type CredentialStore struct{}

func (CredentialStore) brokerageCredentials(profile string) (string, string, error) {
	username := envOrNone("RH_USERNAME")
	password := envOrNone("RH_PASSWORD")
	if username != "" && password != "" {
		return username, password, nil
	}
	storedUser, userErr := keyringGet(brokerageService, profile+":username")
	storedPass, passErr := keyringGet(brokerageService, profile+":password")
	if userErr != nil && password == "" && username == "" {
		return username, password, userErr
	}
	if passErr != nil && password == "" {
		return username, password, passErr
	}
	if username == "" {
		username = storedUser
	}
	if password == "" {
		password = storedPass
	}
	return username, password, nil
}

func (CredentialStore) saveBrokerageCredentials(profile string, username string, password string) error {
	if username == "" || password == "" {
		return nil
	}
	if err := keyringSet(brokerageService, profile+":username", username); err != nil {
		return err
	}
	return keyringSet(brokerageService, profile+":password", password)
}

func (CredentialStore) deleteBrokerageCredentials(profile string) {
	_ = keyringDelete(brokerageService, profile+":username")
	_ = keyringDelete(brokerageService, profile+":password")
}

func (CredentialStore) cryptoCredentials(profile string) (string, string, error) {
	apiKey := envOrNone("RH_CRYPTO_API_KEY")
	privateKey := envOrNone("RH_CRYPTO_PRIVATE_KEY_B64")
	if apiKey != "" && privateKey != "" {
		return apiKey, privateKey, nil
	}
	storedAPI, apiErr := keyringGet(cryptoService, profile+":api_key")
	storedKey, keyErr := keyringGet(cryptoService, profile+":private_key_b64")
	if apiErr != nil && apiKey == "" && privateKey == "" {
		return apiKey, privateKey, apiErr
	}
	if keyErr != nil && privateKey == "" {
		return apiKey, privateKey, keyErr
	}
	if apiKey == "" {
		apiKey = storedAPI
	}
	if privateKey == "" {
		privateKey = storedKey
	}
	return apiKey, privateKey, nil
}

func (CredentialStore) deleteCryptoCredentials(profile string) {
	_ = keyringDelete(cryptoService, profile+":api_key")
	_ = keyringDelete(cryptoService, profile+":private_key_b64")
}

func envOrNone(key string) string {
	return stringsTrim(osGetenv(key))
}

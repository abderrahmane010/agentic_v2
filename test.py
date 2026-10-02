# -*- coding: utf-8 -*-
import dataiku
import pandas as pd
import requests
import os

# Configuration Knox SparkHistory
KNOX_URL = "https://knox.ppd.dlg.net.intra.laposte.fr:8443/gateway/cdp-proxy/spark3history/api/v1/applications"

# Récupérer les credentials depuis les variables d'environnement ou variables Dataiku
username = os.environ.get("KNOX_USER")  # ou ton user en dur
password = os.environ.get("KNOX_PASSWORD")  # depuis ton profil

# Alternative : récupérer depuis les variables projet Dataiku
# variables = dataiku.get_custom_variables()
# username = variables.get("knox_user")
# password = variables.get("knox_password")

# Appel API Knox
response = requests.get(
    KNOX_URL,
    auth=(username, password),
    verify=False  # Si certificat auto-signé, sinon mettre le path du cert
)

# Convertir en DataFrame
if response.status_code == 200:
    applications = response.json()
    test_ael_df = pd.DataFrame(applications)
else:
    raise Exception(f"Erreur API Knox: {response.status_code} - {response.text}")

# Write recipe outputs
test_ael = dataiku.Dataset("test_ael")
test_ael.write_with_schema(test_ael_df)
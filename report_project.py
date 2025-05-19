def select_project_interactive(usages):
    projects = list(usages.keys())
    print("\nProjets disponibles :")
    for i, pid in enumerate(projects, start=1):
        print(f"  {i}. {pid}")
    while True:
        choice = input(f"Choisissez un projet (1-{len(projects)}): ").strip()
        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(projects):
                return projects[idx - 1]
        print("Choix invalide. Veuillez entrer un numéro valide.")
#!/usr/bin/env python3

import subprocess
import sys
import importlib
import json
import os
import re

def print_header(header):
    print("\n" + "=" * 50)
    print(header.center(50))
    print("=" * 50 + "\n")

def install_package(package):
    subprocess.check_call([sys.executable, "-m", "pip", "install", package])

def load_openstack_credentials():
    load_dotenv()  # essaie de charger depuis .env s’il existe

    creds = {
        "auth_url": os.getenv("OS_AUTH_URL"),
        "project_name": os.getenv("OS_PROJECT_NAME"),
        "username": os.getenv("OS_USERNAME"),
        "password": os.getenv("OS_PASSWORD"),
        "user_domain_name": os.getenv("OS_USER_DOMAIN_NAME"),
        "project_domain_name": os.getenv("OS_PROJECT_DOMAIN_NAME"),
    }

    # Si une des variables est absente, on essaie de charger depuis un fichier JSON
    if not all(creds.values()):
        try:
            with open("secrets.json") as f:
                creds = json.load(f)
        except FileNotFoundError:
            raise RuntimeError("Aucun identifiant OpenStack disponible (.env ou secrets.json manquant)")

    return creds

# Fonction pour obtenir les détails d'un projet spécifique
def get_project_details(conn, project_id):
    print_header(f"DÉTAILS DU PROJET AVEC ID: {project_id}")
    project = conn.identity.get_project(project_id)

    if project:
        print(f"ID: {project.id}")
        print(f"Nom: {project.name}")
        print(f"Description: {project.description}")
        print(f"Domaine: {project.domain_id}")
        print(f"Actif: {'Oui' if project.is_enabled else 'Non'}")
    else:
        print(f"Aucun projet trouvé avec l'ID: {project_id}")

# Vérifier et installer les dépendances manquantes
try:
    importlib.import_module('openstack')
except ImportError:
    print("Installation du package openstack...")
    install_package('openstacksdk')

try:
    importlib.import_module('dotenv')
except ImportError:
    print("Installation du package dotenv...")
    install_package('python-dotenv')

from dotenv import load_dotenv
from openstack import connection

# Connexion à OpenStack
creds = load_openstack_credentials()
conn = connection.Connection(**creds)

# Conversion ICU → EUR et CHF
ICU_CONVERSION = {
    "icu_to_eur": 1 / 55.5,  # 1 ICU = 0.018018 EUR
    "icu_to_chf": 1 / 50.0   # 1 ICU = 0.02 CHF
}
ICU_TO_EUR = ICU_CONVERSION["icu_to_eur"]
ICU_TO_CHF = ICU_CONVERSION["icu_to_chf"]

# Fonctions
def get_vm_state(instance_id):
    try:
        result = subprocess.run(
            ["openstack", "server", "show", instance_id],
            capture_output=True, text=True, check=True
        )
        for line in result.stdout.splitlines():
            if line.strip().startswith("OS-EXT-STS:vm_state"):
                # La ligne ressemble à :
                # | OS-EXT-STS:vm_state           | active                               |
                # On récupère la troisième colonne (statut)
                parts = line.split("|")
                if len(parts) >= 3:
                    return parts[2].strip()
        return "INCONNU"
    except subprocess.CalledProcessError as e:
        print(f"Erreur lors de la récupération du statut pour {instance_id}: {e}")
        return "ERREUR"
     
def load_billing(filepath="billing.json"):
    with open(filepath, "r") as f:
        return json.load(f)

def parse_flavor_name(flavor_name):
    # Parse flavor_name du style 'a2-ram4-disk50-perf1'
    match = re.match(r"[a-zA-Z]?(\d+)-ram(\d+)-disk(\d+)", flavor_name)
    if match:
        cpu = int(match.group(1))
        ram = int(match.group(2))
        disk = int(match.group(3))
        return cpu, ram, disk
    return 0, 0, 0

def load_usages(filepath="fetch_uses.json"):
    print(f"Chargement des usages depuis : {filepath}")
    try:
        with open(filepath, "r") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"⚠️ Le fichier {filepath} est introuvable.")
        return {}

    if not data:
        print(f"⚠️ Aucune donnée disponible dans {filepath} (période trop courte ou usages trop faibles).")
        return {}

    usages_by_project = {}

    for entry in data:
        project_id = entry.get("project_id", "inconnu")
        cpu = float(entry.get("cpu", 0))
        ram = float(entry.get("ram", 0))
        storage = float(entry.get("storage", 0))

        if project_id not in usages_by_project:
            usages_by_project[project_id] = {"cpu": 0, "ram": 0, "storage": 0, "icu": 0}

        # Addition des valeurs cumulées
        usages_by_project[project_id]["cpu"] += cpu
        usages_by_project[project_id]["ram"] += ram
        usages_by_project[project_id]["storage"] += storage
        usages_by_project[project_id]["icu"] += float(entry.get("icu", 0))

    return usages_by_project

def aggregate_costs(data):
    costs_by_project = {}

    if not data:
        print("⚠️ Le fichier de facturation est vide.")
        return costs_by_project

    if not isinstance(data, list) or len(data) == 0:
        print("⚠️ Format inattendu ou liste vide dans le fichier de facturation.")
        return costs_by_project

    resources = data[0].get("Resources", [])
    for entry in resources:
        desc = entry.get("desc", {})
        project_id = desc.get("project_id", "inconnu")
        rating = entry.get("rating")
        rate_value = entry.get("rate_value")

        if rating is None:
            continue

        if project_id not in costs_by_project:
            costs_by_project[project_id] = {
                "total_icu": 0.0,
                "rate_values": []
            }

        costs_by_project[project_id]["total_icu"] += float(rating)
        if rate_value is not None:
            costs_by_project[project_id]["rate_values"].append(float(rate_value))

    return costs_by_project

# Affichage du rapport
def main():
    if not conn.authorize():
        print("Échec de la connexion à OpenStack")
        return

    print("Connexion réussie à OpenStack")

    header = r"""
  ___                       _             _                       
 / _ \ _ __   ___ _ __  ___| |_  _ _  ___| | __                   
| | | | '_ \ / _ \ '_ \/ __| __/ _` |/ __| |/ /                   
| |_| | |_) |  __/ | | \__ \ || (_| | (__|   <                    
 \___/| .__/ \___|_| |_|___/\__\__,_|\___|_|\_\               _   
|  _ \|_|__ ___ (_) ___  ___| |_  |  _ \ ___ _ __   ___  _ __| |_ 
| |_) | '__/ _ \| |/ _ \/ __| __| | |_) / _ \ '_ \ / _ \| '__| __|
|  __/| | | (_) | |  __/ (__| |_  |  _ <  __/ |_) | (_) | |  | |_ 
|_|   |_|  \___// |\___|\___|\__| |_| \_\___| .__/ \___/|_|   \__|
              |__/                          |_|                   
                                                       
         Openstack SysAdmin Toolbox

"""
    print(header)

    # Demander la période à l'utilisateur UNE SEULE FOIS
    from datetime import datetime, timedelta, timezone

    def trim_to_minute(dt_str):
        # dt_str est du type '2025-05-19T13:00:00+00:00'
        # On veut '2025-05-19 13:00'
        # Corrige les formats invalides du type '2025-03:01' → '2025-03-01'
        corrected = re.sub(r"(\d{4})-(\d{2}):(\d{2})", r"\1-\2-\3", dt_str[:16])
        dt = datetime.strptime(corrected.replace("T", " "), "%Y-%m-%d %H:%M")
        return dt.strftime("%Y-%m-%d %H:%M")

    def isoformat(dt):
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")

    default_start = isoformat(datetime.now(timezone.utc) - timedelta(hours=2))
    default_end = isoformat(datetime.now(timezone.utc))

    print("Entrez la période souhaitée (format: YYYY-MM-DD HH:MM)")
    start_input = input(f"Date de début [Défaut: {trim_to_minute(default_start)}]: ").strip() or trim_to_minute(default_start)
    end_input = input(f"Date de fin [Défaut: {trim_to_minute(default_end)}, pressez Enter]: ").strip() or trim_to_minute(default_end)

    # Conversion en datetime
    start_dt = datetime.strptime(start_input, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    end_dt = datetime.strptime(end_input, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)

    start_iso = isoformat(start_dt)
    end_iso = isoformat(end_dt)

    # Lancer les scripts pour générer les données
    subprocess.run([sys.executable, 'fetch_uses.py', '--start', start_iso, '--end', end_iso], check=True)
    subprocess.run([sys.executable, 'fetch_billing.py', '--start', start_iso, '--end', end_iso], check=True)

    # Charger usages APRÈS génération
    usages = load_usages("fetch_uses.json")

    if not usages:
        print("⚠️ Aucun usage détecté dans fetch_uses.json, mais on poursuit avec les coûts uniquement.")
        data = load_billing()
        aggregated = aggregate_costs(data)
        if not aggregated:
            print("⚠️ Aucun coût détecté dans la facturation non plus. Fin du programme.")
            return
        projects = list(aggregated.keys())
        print("\nProjets disponibles (coûts) :")
        for i, pid in enumerate(projects, start=1):
            print(f"  {i}. {pid}")
        while True:
            choice = input(f"Choisissez un projet (1-{len(projects)}): ").strip()
            if choice.isdigit():
                idx = int(choice)
                if 1 <= idx <= len(projects):
                    project_id = projects[idx - 1]
                    break
            print("Choix invalide. Veuillez entrer un numéro valide.")
    else:
        print("\nProjets disponibles dans fetch_uses.json :")
        for i, pid in enumerate(usages.keys(), start=1):
            print(f"  {i}. {pid}")
        project_id = select_project_interactive(usages)

    # Charger facturation
    data = load_billing()
    aggregated = aggregate_costs(data)
    # Gérer l'absence de usages : toujours définir usage et cost avec valeurs par défaut si besoin
    usage = usages.get(project_id, {"cpu": 0, "ram": 0, "storage": 0, "icu": 0})
    cost = aggregated.get(project_id, {"total_icu": 0, "rate_values": []})

    # Calcul de la durée entre start_dt et end_dt
    duration = end_dt - start_dt
    days = duration.days
    hours, remainder = divmod(duration.seconds, 3600)
    minutes, _ = divmod(remainder, 60)

    print(f"\n🗓️ Période sélectionnée pour ce projet : {days} jours, {hours} heures, {minutes} minutes\n")

    print("-" * 90)
    print(f"{'Projet':36} | {'CPU':6} | {'RAM':6} | {'Stockage':9} | {'EUR':7} | {'CHF':7}")
    print("-" * 90)

    if project_id in usages or project_id in aggregated:
        icu = cost.get("total_icu", 0)
        eur = icu * ICU_TO_EUR
        chf = icu * ICU_TO_CHF
        print(f"{project_id:36} | {usage['cpu']:6.2f} | {usage['ram']:6.2f} | {usage['storage']:9.2f} | {eur:7.2f} | {chf:7.2f} (ICU: {usage['icu']:.2f})")
        rate_values = cost.get("rate_values", [])
        if rate_values:
            avg_rate_icu = sum(rate_values) / len(rate_values)
            avg_rate_eur = avg_rate_icu * ICU_TO_EUR
            avg_rate_chf = avg_rate_icu * ICU_TO_CHF
            print(f"\n💰 Prix horaire moyen pour ce projet : {avg_rate_eur:.5f} € | {avg_rate_chf:.5f} CHF")
    else:
        print(f"⚠️ Aucun usage ou coût détecté pour le projet (soit usages ou coûts nuls, soit trop faibles) {project_id}.")

    print("Rapport généré avec succès : /tmp/openstack_project_report.txt")

if __name__ == '__main__':
    main()
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
import os
from pathlib import Path

def load_dotenv():
    """Load simple KEY=VALUE entries from the adjacent .env file."""
    env_file = Path(__file__).with_name(".env")
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if separator:
            value = value.strip().strip("\"'")
            os.environ.setdefault(key.strip(), value)

load_dotenv()
# ------------------------------------------------- CONEXIÓN (SSMS local)
# Ajusta SERVER y DATABASE a tu instancia (p. ej. "localhost\\SQLEXPRESS")
password = os.getenv("DB_PASSWORD")
if password is None:
    raise RuntimeError("Falta configurar DB_PASSWORD en el archivo .env")
conn_str = (
     "DRIVER={ODBC Driver 18 for SQL Server};"
    f"SERVER={os.getenv('DB_SERVER')};"
    f"DATABASE={os.getenv('DB_NAME')};"
    f"UID={os.getenv('DB_USER')};"
    f"PWD={os.getenv('DB_PASSWORD')};"
    "Encrypt=no;TrustServerCertificate=yes;"
)
# Para Azure SQL usa en su lugar:
# "SERVER=tu-servidor.database.windows.net;DATABASE=...;UID=usuario;PWD=clave;Encrypt=yes;"
engine = create_engine(URL.create("mssql+pyodbc", query={"odbc_connect": conn_str}))

# ------------------------------------------------- CARGAR TABLAS A PANDAS
def leer(sql):
    return pd.read_sql(sql, engine)

# Se listan columnas (no SELECT *) porque Employee.OrganizationNode es hierarchyid y pyodbc no lo soporta
emp = leer("""SELECT BusinessEntityID, JobTitle, BirthDate, Gender, MaritalStatus, HireDate,
                     SalariedFlag, VacationHours, SickLeaveHours, CurrentFlag
              FROM HumanResources.Employee""")
dep = leer("SELECT DepartmentID, Name AS Departamento, GroupName AS GrupoDepartamento "
           "FROM HumanResources.Department")
edh = leer("SELECT BusinessEntityID, DepartmentID, ShiftID, StartDate, EndDate "
           "FROM HumanResources.EmployeeDepartmentHistory")
pay = leer("SELECT BusinessEntityID, RateChangeDate, Rate, PayFrequency "
           "FROM HumanResources.EmployeePayHistory")
shift = leer("SELECT ShiftID, Name AS Turno FROM HumanResources.Shift")

for nombre, t in {"Employee": emp, "Department": dep, "EmployeeDepartmentHistory": edh,
                  "EmployeePayHistory": pay, "Shift": shift}.items():
    print(f"{nombre:28s} {t.shape}")

# ---------------------------------------------------------------- JOINS
edh_actual = edh[edh["EndDate"].isna()]                                  # departamento vigente
pay_ultima = (pay.sort_values("RateChangeDate")
                 .groupby("BusinessEntityID").tail(1)                    # última tarifa
                 .rename(columns={"Rate": "Tarifa"}))

dataset = (
    emp[emp["CurrentFlag"]]
    .merge(edh_actual[["BusinessEntityID", "DepartmentID", "ShiftID"]],
           on="BusinessEntityID", how="inner", validate="one_to_one")
    .merge(dep, on="DepartmentID", how="left", validate="many_to_one")
    .merge(shift, on="ShiftID", how="left", validate="many_to_one")
    .merge(pay_ultima[["BusinessEntityID", "Tarifa", "PayFrequency"]],
           on="BusinessEntityID", how="left", validate="one_to_one")
)

columnas = ["BusinessEntityID", "JobTitle", "BirthDate", "Gender", "MaritalStatus", "HireDate",
            "SalariedFlag", "VacationHours", "SickLeaveHours", "Departamento",
            "GrupoDepartamento", "Turno", "Tarifa", "PayFrequency"]
dataset = dataset[columnas].copy()

# ------------------------------------------------------ TIPOS DE DATOS
dataset["Tarifa"] = dataset["Tarifa"].astype(float)          # money llega como Decimal
dataset["BirthDate"] = pd.to_datetime(dataset["BirthDate"])
dataset["HireDate"] = pd.to_datetime(dataset["HireDate"])

# ------------------------------------------------------------ VALIDACIÓN
assert dataset["BusinessEntityID"].is_unique, "Hay empleados duplicados: revisa los joins"
assert len(dataset) == emp["CurrentFlag"].sum(), "Se perdieron o sobraron empleados activos"
assert dataset.isna().sum().sum() == 0, "Hay valores nulos tras los joins"
print("Validaciones OK:", dataset.shape)

# ---------------------------------------------------------- DATASET FINAL
dataset.to_csv("dataset.csv", index=False, encoding="utf-8-sig")
print("dataset.csv guardado")
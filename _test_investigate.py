import config
from data.warehouse import ensure_database
from ai.agent import DataReliabilityAgent
from data.incidents import build_sample_incident_payload
from ai.schemas import IncidentInput

ensure_database(config.DUCKDB_PATH)
agent = DataReliabilityAgent()
print('Agent mode:', agent.mode)
payload = build_sample_incident_payload()
incident = IncidentInput(**payload)
agent.load_incident(incident)
report = agent.investigate()
print('Investigate OK!')
print('Incident ID:', report.incident_id)
print('Target Table:', report.target_table)
print('Action type:', report.remediation.action_type)
print('Statements count:', len(report.remediation.sql_statements))

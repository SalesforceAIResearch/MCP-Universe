"""
An MCP server for persistent memory using a knowledge graph
"""
import os
import json
from pathlib import Path
from typing import Union, Any, Dict, List
import click
from mcp.server.fastmcp import FastMCP
from mcpuniverse.common.logger import get_logger


class Entity:
    def __init__(self, name: str, entity_type: str, observations: List[str]):
        self.name = name
        self.entity_type = entity_type
        self.observations = observations

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "entity",
            "name": self.name,
            "entityType": self.entity_type,
            "observations": self.observations
        }


class Relation:
    def __init__(self, from_entity: str, to_entity: str, relation_type: str):
        self.from_entity = from_entity
        self.to_entity = to_entity
        self.relation_type = relation_type

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "relation",
            "from": self.from_entity,
            "to": self.to_entity,
            "relationType": self.relation_type
        }


class KnowledgeGraph:
    def __init__(self, entities: List[Entity], relations: List[Relation]):
        self.entities = entities
        self.relations = relations

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entities": [
                {"name": e.name, "entityType": e.entity_type, "observations": e.observations}
                for e in self.entities
            ],
            "relations": [
                {"from": r.from_entity, "to": r.to_entity, "relationType": r.relation_type}
                for r in self.relations
            ]
        }


class KnowledgeGraphManager:
    def __init__(self, memory_file_path: str):
        self.memory_file_path = memory_file_path

    def load_graph(self) -> KnowledgeGraph:
        """Load the knowledge graph from file"""
        entities = []
        relations = []
        
        if not Path(self.memory_file_path).exists():
            return KnowledgeGraph(entities, relations)
        
        try:
            with open(self.memory_file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    item = json.loads(line)
                    if item.get("type") == "entity":
                        entities.append(Entity(
                            item["name"],
                            item["entityType"],
                            item["observations"]
                        ))
                    elif item.get("type") == "relation":
                        relations.append(Relation(
                            item["from"],
                            item["to"],
                            item["relationType"]
                        ))
        except Exception as e:
            raise Exception(f"Error loading graph: {e}")
        
        return KnowledgeGraph(entities, relations)

    def save_graph(self, graph: KnowledgeGraph) -> None:
        """Save the knowledge graph to file"""
        lines = []
        for entity in graph.entities:
            lines.append(json.dumps(entity.to_dict()))
        for relation in graph.relations:
            lines.append(json.dumps(relation.to_dict()))
        
        with open(self.memory_file_path, 'w') as f:
            f.write('\n'.join(lines))

    def create_entities(self, entities_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Create new entities"""
        graph = self.load_graph()
        existing_names = {e.name for e in graph.entities}
        
        new_entities = []
        for entity_data in entities_data:
            if entity_data["name"] not in existing_names:
                entity = Entity(
                    entity_data["name"],
                    entity_data["entityType"],
                    entity_data["observations"]
                )
                graph.entities.append(entity)
                new_entities.append({
                    "name": entity.name,
                    "entityType": entity.entity_type,
                    "observations": entity.observations
                })
        
        self.save_graph(graph)
        return new_entities

    def create_relations(self, relations_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Create new relations"""
        graph = self.load_graph()
        
        existing_relations = {
            (r.from_entity, r.to_entity, r.relation_type) for r in graph.relations
        }
        
        new_relations = []
        for relation_data in relations_data:
            rel_tuple = (relation_data["from"], relation_data["to"], relation_data["relationType"])
            if rel_tuple not in existing_relations:
                relation = Relation(
                    relation_data["from"],
                    relation_data["to"],
                    relation_data["relationType"]
                )
                graph.relations.append(relation)
                new_relations.append({
                    "from": relation.from_entity,
                    "to": relation.to_entity,
                    "relationType": relation.relation_type
                })
        
        self.save_graph(graph)
        return new_relations

    def add_observations(self, observations_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Add observations to existing entities"""
        graph = self.load_graph()
        results = []
        
        for obs_data in observations_data:
            entity_name = obs_data["entityName"]
            entity = next((e for e in graph.entities if e.name == entity_name), None)
            
            if not entity:
                raise Exception(f"Entity with name {entity_name} not found")
            
            new_observations = [
                content for content in obs_data["contents"]
                if content not in entity.observations
            ]
            entity.observations.extend(new_observations)
            
            results.append({
                "entityName": entity_name,
                "addedObservations": new_observations
            })
        
        self.save_graph(graph)
        return results

    def delete_entities(self, entity_names: List[str]) -> None:
        """Delete entities and their relations"""
        graph = self.load_graph()
        graph.entities = [e for e in graph.entities if e.name not in entity_names]
        graph.relations = [
            r for r in graph.relations
            if r.from_entity not in entity_names and r.to_entity not in entity_names
        ]
        self.save_graph(graph)

    def delete_observations(self, deletions: List[Dict[str, Any]]) -> None:
        """Delete specific observations from entities"""
        graph = self.load_graph()
        
        for deletion in deletions:
            entity = next((e for e in graph.entities if e.name == deletion["entityName"]), None)
            if entity:
                entity.observations = [
                    obs for obs in entity.observations
                    if obs not in deletion["observations"]
                ]
        
        self.save_graph(graph)

    def delete_relations(self, relations_data: List[Dict[str, Any]]) -> None:
        """Delete specific relations"""
        graph = self.load_graph()
        
        relations_to_delete = {
            (r["from"], r["to"], r["relationType"]) for r in relations_data
        }
        
        graph.relations = [
            r for r in graph.relations
            if (r.from_entity, r.to_entity, r.relation_type) not in relations_to_delete
        ]
        
        self.save_graph(graph)

    def read_graph(self) -> Dict[str, Any]:
        """Read the entire knowledge graph"""
        graph = self.load_graph()
        return graph.to_dict()

    def search_nodes(self, query: str) -> Dict[str, Any]:
        """Search for nodes in the knowledge graph"""
        graph = self.load_graph()
        query_lower = query.lower()
        
        filtered_entities = [
            e for e in graph.entities
            if query_lower in e.name.lower() or
               query_lower in e.entity_type.lower() or
               any(query_lower in obs.lower() for obs in e.observations)
        ]
        
        filtered_entity_names = {e.name for e in filtered_entities}
        
        filtered_relations = [
            r for r in graph.relations
            if r.from_entity in filtered_entity_names and r.to_entity in filtered_entity_names
        ]
        
        filtered_graph = KnowledgeGraph(filtered_entities, filtered_relations)
        return filtered_graph.to_dict()

    def open_nodes(self, names: List[str]) -> Dict[str, Any]:
        """Open specific nodes by name"""
        graph = self.load_graph()
        
        filtered_entities = [e for e in graph.entities if e.name in names]
        filtered_entity_names = {e.name for e in filtered_entities}
        
        filtered_relations = [
            r for r in graph.relations
            if r.from_entity in filtered_entity_names and r.to_entity in filtered_entity_names
        ]
        
        filtered_graph = KnowledgeGraph(filtered_entities, filtered_relations)
        return filtered_graph.to_dict()


def build_server(port: int) -> FastMCP:
    """
    Initializes the MCP server.

    :param port: Port for SSE.
    :return: The MCP server.
    """
    # Get memory file path from environment or use default
    default_path = Path(__file__).parent / "memory.jsonl"
    memory_file_path = os.getenv("MEMORY_FILE_PATH", str(default_path))
    
    # Make path absolute if it's relative
    if not Path(memory_file_path).is_absolute():
        memory_file_path = str(Path(__file__).parent / memory_file_path)
    
    manager = KnowledgeGraphManager(memory_file_path)
    mcp = FastMCP("memory", port=port)

    @mcp.tool()
    async def create_entities(entities: List[Dict[str, Any]]) -> str:
        """
        Create multiple new entities in the knowledge graph.

        Args:
            entities: List of entities to create. Each entity should have:
                - name: The name of the entity
                - entityType: The type of the entity
                - observations: List of observation strings
        """
        try:
            result = manager.create_entities(entities)
            return json.dumps(result, indent=2)
        except Exception as e:
            return f"Error creating entities: {str(e)}"

    @mcp.tool()
    async def create_relations(relations: List[Dict[str, Any]]) -> str:
        """
        Create multiple new relations between entities in the knowledge graph.

        Args:
            relations: List of relations to create. Each relation should have:
                - from: The name of the source entity
                - to: The name of the target entity
                - relationType: The type of the relation (in active voice)
        """
        try:
            result = manager.create_relations(relations)
            return json.dumps(result, indent=2)
        except Exception as e:
            return f"Error creating relations: {str(e)}"

    @mcp.tool()
    async def add_observations(observations: List[Dict[str, Any]]) -> str:
        """
        Add new observations to existing entities in the knowledge graph.

        Args:
            observations: List of observations to add. Each item should have:
                - entityName: The name of the entity to add observations to
                - contents: List of observation strings to add
        """
        try:
            result = manager.add_observations(observations)
            return json.dumps(result, indent=2)
        except Exception as e:
            return f"Error adding observations: {str(e)}"

    @mcp.tool()
    async def delete_entities(entityNames: List[str]) -> str:
        """
        Delete multiple entities and their associated relations from the knowledge graph.

        Args:
            entityNames: List of entity names to delete
        """
        try:
            manager.delete_entities(entityNames)
            return "Entities deleted successfully"
        except Exception as e:
            return f"Error deleting entities: {str(e)}"

    @mcp.tool()
    async def delete_observations(deletions: List[Dict[str, Any]]) -> str:
        """
        Delete specific observations from entities in the knowledge graph.

        Args:
            deletions: List of deletions. Each item should have:
                - entityName: The name of the entity
                - observations: List of observation strings to delete
        """
        try:
            manager.delete_observations(deletions)
            return "Observations deleted successfully"
        except Exception as e:
            return f"Error deleting observations: {str(e)}"

    @mcp.tool()
    async def delete_relations(relations: List[Dict[str, Any]]) -> str:
        """
        Delete multiple relations from the knowledge graph.

        Args:
            relations: List of relations to delete. Each relation should have:
                - from: The name of the source entity
                - to: The name of the target entity
                - relationType: The type of the relation
        """
        try:
            manager.delete_relations(relations)
            return "Relations deleted successfully"
        except Exception as e:
            return f"Error deleting relations: {str(e)}"

    @mcp.tool()
    async def read_graph() -> str:
        """
        Read the entire knowledge graph.

        Returns the complete graph structure with all entities and relations.
        """
        try:
            result = manager.read_graph()
            return json.dumps(result, indent=2)
        except Exception as e:
            return f"Error reading graph: {str(e)}"

    @mcp.tool()
    async def search_nodes(query: str) -> str:
        """
        Search for nodes in the knowledge graph based on a query.

        Args:
            query: The search query to match against entity names, types, and observations

        Returns matching entities and their relations.
        """
        try:
            result = manager.search_nodes(query)
            return json.dumps(result, indent=2)
        except Exception as e:
            return f"Error searching nodes: {str(e)}"

    @mcp.tool()
    async def open_nodes(names: List[str]) -> str:
        """
        Open specific nodes in the knowledge graph by their names.

        Args:
            names: List of entity names to retrieve

        Returns the requested entities and relations between them.
        """
        try:
            result = manager.open_nodes(names)
            return json.dumps(result, indent=2)
        except Exception as e:
            return f"Error opening nodes: {str(e)}"

    return mcp


@click.command()
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse"]),
    default="stdio",
    help="Transport type",
)
@click.option("--port", default="8000", help="Port to listen on for SSE")
def main(transport: str, port: str):
    """
    Starts the initialized MCP server.

    :param port: Port for SSE.
    :param transport: The transport type, e.g., `stdio` or `sse`.
    :return:
    """
    assert transport.lower() in ["stdio", "sse"], \
        "Transport should be `stdio` or `sse`"
    logger = get_logger("Service:memory")
    logger.info("Starting the MCP server")
    mcp = build_server(int(port))
    mcp.run(transport=transport.lower())

from dataclasses import dataclass
from typing import Dict, Any, Optional, List, Union, Literal
from .exceptions import SailhouseError
import requests


@dataclass
class FilterCondition:
    path: str
    condition: str
    value: Any


@dataclass 
class ComplexFilter:
    conditions: List[FilterCondition]
    operator: Literal["and", "or"] = "and"


# Union type for filters - can be boolean, None, or complex filter
Filter = Union[bool, None, ComplexFilter]


@dataclass
class RegisterResult:
    outcome: Literal["created", "updated", "none"]


class AdminClient:
    def __init__(self, sailhouse_client: 'SailhouseClient'):
        self._client = sailhouse_client
        
    def register_push_subscription(
        self,
        topic: str,
        subscription: str,
        endpoint: str,
        **kwargs
    ) -> RegisterResult:
        """Register a push subscription for webhook delivery"""
        url = f"{self._client.base_url}/admin/topics/{topic}/subscriptions/{subscription}/push"
        
        body: Dict[str, Any] = {
            "endpoint": endpoint
        }
        
        # Handle optional parameters
        filter_condition = kwargs.get('filter_condition')
        rate_limit = kwargs.get('rate_limit')
        deduplication = kwargs.get('deduplication')
        
        # Handle filter_condition - only add to body if explicitly provided
        if 'filter_condition' in kwargs:
            if isinstance(filter_condition, bool):
                body["filter"] = filter_condition
            elif filter_condition is None:
                body["filter"] = None
            elif isinstance(filter_condition, ComplexFilter):
                body["filter"] = {
                    "conditions": [
                        {
                            "path": cond.path,
                            "condition": cond.condition,
                            "value": cond.value
                        }
                        for cond in filter_condition.conditions
                    ],
                    "operator": filter_condition.operator
                }
        
        if rate_limit is not None:
            body["rate_limit"] = rate_limit
            
        if deduplication is not None:
            body["deduplication"] = deduplication
        
        response = self._client.session.post(
            url,
            json=body,
            timeout=self._client.timeout
        )
        
        if response.status_code not in (200, 201):
            raise SailhouseError(
                f"Failed to register push subscription: {response.status_code} - {response.text}"
            )
        
        data = response.json()
        return RegisterResult(outcome=data.get("outcome", "none"))
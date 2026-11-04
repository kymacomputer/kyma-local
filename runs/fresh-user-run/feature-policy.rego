package kyma.feature
import rego.v1
default enabled := false
enabled if {
    some rule in data.kyma_feature_rules.rules
    rule.proposed_eligible
    input.customer_id == rule.customer_id
    input.operation_id == rule.operation_id
    every key, value in rule.required_facts {
        input.facts[key] == value
    }
}

# S1 API Boundary

S1 API modules should call shared backend clients and return raw response data to
adapters. React components should not import these modules directly unless the
result has already been mapped into an S1 view model.

block:
  name: string
  version: string
  description: string

  inputs:
    - name: string
      type: string        # message type or data type
      required: boolean

  outputs:
    - name: string
      type: string

  params:
    - name: string
      type: int | float | string | bool
      default: any
      description: string

  runtime:
    entrypoint: string    # python module or command
    supports_sim: boolean

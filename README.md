PyPred
======
This is a fork of [@armon/pypred](https://github.com/armon/pypred). It supports additional features:

- Identifier resolution of type list and object, e.g: jobs.0 will be equals to jobs[0]
- Mathematics operators: +,-,\*,/. You can write something like age + 5 <= senior_age
- Retrieval of raw value of evaluation, so you can use it to do calculation, e.g: (age + 5) * 2

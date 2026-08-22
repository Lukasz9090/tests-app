# Test Plan: SimpleCalculatorService
Status: draft before confidence pass; 10 scenarios, 0 deferred. Legacy characterization of current implementation behavior, with focus on all visible branches (division by zero, null handling, palindrome case-insensitive comparison).

```json
{
  "schema_version": 1,
  "plan_version": 1,
  "target": {
    "class": "SimpleCalculatorService"
  },
  "mode": "legacy",
  "characterization": true,
  "status": "READY",
  "context": {
    "source_roots": [
      "src/main/java"
    ],
    "test_roots": [
      "src/test/java"
    ],
    "related_classes": [],
    "existing_tests": [],
    "builders": [],
    "fixtures": [],
    "relevant_enums": [],
    "notes": [
      "Repository is single-module Maven project (owner module: tests-app via root pom.xml).",
      "JUnit 5 is available transitively via org.springframework.boot:spring-boot-starter-test (test scope).",
      "JaCoCo plugin is not configured in pom.xml; invocation mode resolved as fully-qualified Maven goals.",
      "Legacy freshness guard: target file has no local uncommitted changes, last commit age was 46 minutes; user explicitly confirmed continuing in legacy mode despite freshness risk.",
      "Context pack built via .github/agents/test-planner/scripts/build_context.py with target SimpleCalculatorService."
    ]
  },
  "scenarios": [
    {
      "id": "TC01",
      "change": "NEW",
      "description": "add returns arithmetic sum for two integers",
      "priority": "high",
      "data": {
        "operands": {
          "source": "usage",
          "ref": "SimpleCalculatorService#add",
          "variant": "any int first, any int second"
        }
      },
      "implementation_hints": {
        "test_class": "SimpleCalculatorServiceTest",
        "test_method": "shouldAddTwoIntegers",
        "test_file": "src/test/java/com/testsapp/service/SimpleCalculatorServiceTest.java"
      },
      "evidence": [
        {
          "type": "usage",
          "ref": "SimpleCalculatorService#add"
        },
        {
          "type": "usage",
          "ref": "src/main/java/com/testsapp/service/SimpleCalculatorService.java:9"
        }
      ],
      "confidence": 0.64,
      "evidence_strength": "medium"
    },
    {
      "id": "TC02",
      "change": "NEW",
      "description": "subtract returns arithmetic difference for two integers",
      "priority": "high",
      "data": {
        "operands": {
          "source": "usage",
          "ref": "SimpleCalculatorService#subtract",
          "variant": "any int first, any int second"
        }
      },
      "implementation_hints": {
        "test_class": "SimpleCalculatorServiceTest",
        "test_method": "shouldSubtractTwoIntegers",
        "test_file": "src/test/java/com/testsapp/service/SimpleCalculatorServiceTest.java"
      },
      "evidence": [
        {
          "type": "usage",
          "ref": "SimpleCalculatorService#subtract"
        },
        {
          "type": "usage",
          "ref": "src/main/java/com/testsapp/service/SimpleCalculatorService.java:13"
        }
      ],
      "confidence": 0.64,
      "evidence_strength": "medium"
    },
    {
      "id": "TC03",
      "change": "NEW",
      "description": "multiply returns arithmetic product for two integers",
      "priority": "high",
      "data": {
        "operands": {
          "source": "usage",
          "ref": "SimpleCalculatorService#multiply",
          "variant": "any int first, any int second"
        }
      },
      "implementation_hints": {
        "test_class": "SimpleCalculatorServiceTest",
        "test_method": "shouldMultiplyTwoIntegers",
        "test_file": "src/test/java/com/testsapp/service/SimpleCalculatorServiceTest.java"
      },
      "evidence": [
        {
          "type": "usage",
          "ref": "SimpleCalculatorService#multiply"
        },
        {
          "type": "usage",
          "ref": "src/main/java/com/testsapp/service/SimpleCalculatorService.java:17"
        }
      ],
      "confidence": 0.64,
      "evidence_strength": "medium"
    },
    {
      "id": "TC04",
      "change": "NEW",
      "description": "divide returns integer quotient when divider is non-zero",
      "priority": "high",
      "data": {
        "operands": {
          "source": "usage",
          "ref": "SimpleCalculatorService#divide",
          "variant": "any int first, non-zero int second"
        }
      },
      "implementation_hints": {
        "test_class": "SimpleCalculatorServiceTest",
        "test_method": "shouldDivideWhenDividerIsNonZero",
        "test_file": "src/test/java/com/testsapp/service/SimpleCalculatorServiceTest.java"
      },
      "evidence": [
        {
          "type": "usage",
          "ref": "SimpleCalculatorService#divide"
        },
        {
          "type": "usage",
          "ref": "src/main/java/com/testsapp/service/SimpleCalculatorService.java:24"
        }
      ],
      "confidence": 0.64,
      "evidence_strength": "medium"
    },
    {
      "id": "TC05",
      "change": "NEW",
      "description": "divide throws IllegalArgumentException with fixed message when divider is zero",
      "priority": "high",
      "data": {
        "divider": {
          "source": "usage",
          "ref": "src/main/java/com/testsapp/service/SimpleCalculatorService.java:21",
          "variant": "exactly zero"
        },
        "exception_message": {
          "source": "usage",
          "ref": "src/main/java/com/testsapp/service/SimpleCalculatorService.java:22",
          "value": "Divider cannot be zero"
        }
      },
      "implementation_hints": {
        "test_class": "SimpleCalculatorServiceTest",
        "test_method": "shouldThrowWhenDividerIsZero",
        "test_file": "src/test/java/com/testsapp/service/SimpleCalculatorServiceTest.java"
      },
      "evidence": [
        {
          "type": "usage",
          "ref": "src/main/java/com/testsapp/service/SimpleCalculatorService.java:21"
        },
        {
          "type": "usage",
          "ref": "src/main/java/com/testsapp/service/SimpleCalculatorService.java:22"
        }
      ],
      "confidence": 0.64,
      "evidence_strength": "medium"
    },
    {
      "id": "TC06",
      "change": "NEW",
      "description": "reverseString returns null for null input",
      "priority": "high",
      "data": {
        "input": {
          "source": "usage",
          "ref": "src/main/java/com/testsapp/service/SimpleCalculatorService.java:28",
          "variant": "null"
        }
      },
      "implementation_hints": {
        "test_class": "SimpleCalculatorServiceTest",
        "test_method": "shouldReturnNullWhenReverseInputIsNull",
        "test_file": "src/test/java/com/testsapp/service/SimpleCalculatorServiceTest.java"
      },
      "evidence": [
        {
          "type": "usage",
          "ref": "SimpleCalculatorService#reverseString"
        },
        {
          "type": "usage",
          "ref": "src/main/java/com/testsapp/service/SimpleCalculatorService.java:29"
        }
      ],
      "confidence": 0.64,
      "evidence_strength": "medium"
    },
    {
      "id": "TC07",
      "change": "NEW",
      "description": "reverseString inverts character order for non-null input",
      "priority": "medium",
      "data": {
        "input": {
          "source": "usage",
          "ref": "SimpleCalculatorService#reverseString",
          "variant": "non-null string"
        }
      },
      "implementation_hints": {
        "test_class": "SimpleCalculatorServiceTest",
        "test_method": "shouldReverseNonNullString",
        "test_file": "src/test/java/com/testsapp/service/SimpleCalculatorServiceTest.java"
      },
      "evidence": [
        {
          "type": "usage",
          "ref": "src/main/java/com/testsapp/service/SimpleCalculatorService.java:36"
        },
        {
          "type": "usage",
          "ref": "src/main/java/com/testsapp/service/SimpleCalculatorService.java:44"
        }
      ],
      "confidence": 0.64,
      "evidence_strength": "medium"
    },
    {
      "id": "TC08",
      "change": "NEW",
      "description": "isPalindrome returns false for null input",
      "priority": "high",
      "data": {
        "input": {
          "source": "usage",
          "ref": "src/main/java/com/testsapp/service/SimpleCalculatorService.java:48",
          "variant": "null"
        }
      },
      "implementation_hints": {
        "test_class": "SimpleCalculatorServiceTest",
        "test_method": "shouldReturnFalseForNullPalindromeInput",
        "test_file": "src/test/java/com/testsapp/service/SimpleCalculatorServiceTest.java"
      },
      "evidence": [
        {
          "type": "usage",
          "ref": "SimpleCalculatorService#isPalindrome"
        },
        {
          "type": "usage",
          "ref": "src/main/java/com/testsapp/service/SimpleCalculatorService.java:49"
        }
      ],
      "confidence": 0.64,
      "evidence_strength": "medium"
    },
    {
      "id": "TC09",
      "change": "NEW",
      "description": "isPalindrome uses case-insensitive comparison against reversed input",
      "priority": "medium",
      "data": {
        "input": {
          "source": "usage",
          "ref": "src/main/java/com/testsapp/service/SimpleCalculatorService.java:52",
          "variant": "string equal to its reverse ignoring case"
        }
      },
      "implementation_hints": {
        "test_class": "SimpleCalculatorServiceTest",
        "test_method": "shouldTreatCaseDifferencesAsPalindrome",
        "test_file": "src/test/java/com/testsapp/service/SimpleCalculatorServiceTest.java"
      },
      "evidence": [
        {
          "type": "usage",
          "ref": "src/main/java/com/testsapp/service/SimpleCalculatorService.java:52"
        },
        {
          "type": "usage",
          "ref": "SimpleCalculatorService#reverseString"
        }
      ],
      "confidence": 0.64,
      "evidence_strength": "medium"
    },
    {
      "id": "TC10",
      "change": "NEW",
      "description": "isPalindrome returns false when value differs from its reversed form",
      "priority": "medium",
      "data": {
        "input": {
          "source": "usage",
          "ref": "src/main/java/com/testsapp/service/SimpleCalculatorService.java:52",
          "variant": "string not equal to its reverse even ignoring case"
        }
      },
      "implementation_hints": {
        "test_class": "SimpleCalculatorServiceTest",
        "test_method": "shouldReturnFalseForNonPalindrome",
        "test_file": "src/test/java/com/testsapp/service/SimpleCalculatorServiceTest.java"
      },
      "evidence": [
        {
          "type": "usage",
          "ref": "SimpleCalculatorService#isPalindrome"
        },
        {
          "type": "usage",
          "ref": "src/main/java/com/testsapp/service/SimpleCalculatorService.java:52"
        }
      ],
      "confidence": 0.64,
      "evidence_strength": "medium"
    }
  ],
  "deferred": []
}
```
